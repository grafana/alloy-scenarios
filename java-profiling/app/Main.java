import java.util.ArrayDeque;

/**
 * Deterministic JVM workload for the java-profiling scenario.
 *
 * Two daemon threads give the profiler something recognizable to attribute:
 *  - burnCpu: tight prime-counting loops, so the CPU flame graph is
 *    dominated by Main.burnCpu / Main.countPrimes.
 *  - churnAllocations: steady byte[] churn through a bounded ring, so the
 *    allocation profile (alloc_in_new_tlab) is dominated by
 *    Main.churnAllocations.
 */
public class Main {

    // Results are published into this sink so the JIT can't elide the work.
    private static volatile long sink;

    public static void main(String[] args) throws InterruptedException {
        Thread cpu = new Thread(Main::burnCpu, "cpu-burner");
        cpu.setDaemon(true);
        cpu.start();

        Thread alloc = new Thread(Main::churnAllocations, "alloc-churner");
        alloc.setDaemon(true);
        alloc.start();

        // Heartbeat keeps the container's main process alive forever and
        // gives `docker logs` a sign of life.
        while (true) {
            System.out.println("java-app alive; sink=" + sink);
            Thread.sleep(30_000);
        }
    }

    private static void burnCpu() {
        while (true) {
            sink = countPrimes(50_000);
        }
    }

    private static long countPrimes(int limit) {
        long count = 0;
        for (int n = 2; n < limit; n++) {
            if (isPrime(n)) {
                count++;
            }
        }
        return count;
    }

    private static boolean isPrime(int n) {
        for (int d = 2; (long) d * d <= n; d++) {
            if (n % d == 0) {
                return false;
            }
        }
        return true;
    }

    private static void churnAllocations() {
        ArrayDeque<byte[]> ring = new ArrayDeque<>();
        while (true) {
            byte[] block = new byte[256 * 1024];
            block[0] = 1;
            ring.addLast(block);
            if (ring.size() > 32) {
                ring.removeFirst();
            }
            sink += block.length;
            try {
                Thread.sleep(5);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }
}
