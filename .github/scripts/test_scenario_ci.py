"""Regression tests for the catalog contract and affected-scenario selection."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml
import generate_scenarios_docs as docs
from select_scenarios import select_scenarios


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'nested/demo').mkdir(parents=True)
        (self.root / 'nested/demo/docker-compose.yml').write_text('services: {}\n')
        self.scenario = dict(name='Demo', path='nested/demo', description='Demo.', ci='smoke')

    def load(self, scenarios):
        source = self.root / 'scenarios.yml'
        source.write_text(yaml.safe_dump({'categories': [dict(
            slug='demo', title='Demo', intro='Demo.', scenarios=scenarios)]}))
        with patch.object(docs, 'ROOT', self.root):
            return docs.load(source)

    def test_nested_smoke_is_generated(self):
        self.assertEqual(docs.render_ci_list(self.load([self.scenario])), 'nested/demo\n')

    def test_explicit_skip_remains_documented(self):
        self.scenario['ci'] = {'skip': 'Needs a cluster.'}
        categories = self.load([self.scenario])
        self.assertEqual(docs.render_ci_list(categories), '')
        self.assertIn('nested/demo', docs.render_docs(categories[0]))

    def test_invalid_policies_fail(self):
        for policy in [None, False, 'skip', {}, {'skip': ''}, {'skip': 'Reason', 'typo': True}]:
            with self.subTest(policy=policy):
                self.scenario['ci'] = policy
                with self.assertRaises(SystemExit):
                    self.load([self.scenario])

    def test_missing_policy_fails(self):
        del self.scenario['ci']
        with self.assertRaisesRegex(SystemExit, "missing 'ci'"):
            self.load([self.scenario])

    def test_smoke_requires_compose(self):
        (self.root / 'nested/demo/docker-compose.yml').unlink()
        with self.assertRaisesRegex(SystemExit, 'requires a docker-compose'):
            self.load([self.scenario])

    def test_duplicate_paths_fail(self):
        other = dict(self.scenario, name='Other')
        with self.assertRaisesRegex(SystemExit, 'duplicate path'):
            self.load([self.scenario, other])

    def test_stale_ci_list_fails_check(self):
        categories = self.load([self.scenario])
        readme = self.root / 'README.md'
        readme.write_text(docs.render_readme_block(categories)[0] + '\n' + docs.END)
        readme.write_text(docs.render_readme(readme.read_text(), categories))
        output = self.root / 'docs'
        output.mkdir()
        (output / 'demo.md').write_text(docs.render_docs(categories[0]))
        ci_list = self.root / 'scenario-list.txt'
        ci_list.write_text('wrong\n')
        with patch.multiple(docs, ROOT=self.root, SOURCE=self.root / 'scenarios.yml',
                            README=readme, DOCS_DIR=output, CI_LIST=ci_list), \
                patch('sys.argv', ['generate', '--check']):
            self.assertEqual(docs.main(), 1)
            self.assertEqual(ci_list.read_text(), 'wrong\n')


class SelectionTests(unittest.TestCase):
    scenarios = ['logs', 'nested/demo', 'nested/demo-other']

    def test_nested_and_top_level_changes(self):
        self.assertEqual(select_scenarios(self.scenarios, ['nested/demo/app/main.py', 'logs/config.alloy']),
                         ['logs', 'nested/demo'])

    def test_directory_boundaries(self):
        self.assertEqual(select_scenarios(self.scenarios, ['nested/demo-other/config.alloy']), ['nested/demo-other'])

    def test_deleted_and_renamed_files(self):
        self.assertEqual(select_scenarios(self.scenarios, ['nested/demo/old', 'logs/new']), ['logs', 'nested/demo'])

    def test_shared_changes_select_all(self):
        for path in ['image-versions.env', 'run-example.sh', 'scenarios.yml', '.github/scenario-list.txt']:
            with self.subTest(path=path):
                self.assertEqual(select_scenarios(self.scenarios, [path]), self.scenarios)

    def test_unrelated_and_empty_changes(self):
        for changed in [[], ['README.md'], ['skipped/config.alloy']]:
            self.assertEqual(select_scenarios(self.scenarios, changed), [])


class LauncherTests(unittest.TestCase):
    def test_image_versions_resolve_for_top_level_and_nested_scenarios(self):
        script = docs.ROOT / 'run-example.sh'
        with tempfile.TemporaryDirectory(prefix='scenario test ') as directory:
            root = Path(directory)
            (root / 'image-versions.env').write_text('ALLOY_VERSION=test\n')
            (root / 'bin').mkdir()
            docker = root / 'bin/docker'
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" > "$CAPTURE"\n')
            docker.chmod(0o755)
            for scenario in ['demo', 'nested/demo']:
                (root / scenario).mkdir(parents=True)
                (root / scenario / 'docker-compose.yml').write_text('services: {}\n')
                capture = root / 'capture'
                env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'], CAPTURE=str(capture))
                subprocess.run(['bash', str(script), scenario], cwd=root, env=env, check=True, capture_output=True)
                args = capture.read_text().splitlines()
                self.assertEqual(Path(args[0]).resolve(), (root / scenario).resolve())
                env_path = Path(args[args.index('--env-file') + 1])
                self.assertEqual(env_path.resolve(), (root / 'image-versions.env').resolve())
                self.assertTrue(env_path.is_file())


if __name__ == '__main__':
    unittest.main()
