-- Fixture B: Night Elf druid "Morrow" on Emberfall (US), starting in Teldrassil.
-- Mana, then Cat Form energy; restricted health during combat; two sessions
-- in one save, the second started after a reload.
H.character({
    regionId = 1, realm = "Emberfall", name = "Morrow", guid = "Player-2002-0F00BA44",
    raceName = "Night Elf", raceFile = "NightElf", raceId = 4, className = "Druid",
    classFile = "DRUID", classId = 11, faction = "Alliance",
    level = 12, xp = 0, xpMax = 8800, hp = 310, hpMax = 310,
    powerType = 0, powerToken = "MANA", power = 420, powerMax = 420, money = 1534,
    map = 1438, zone = "Teldrassil", x = 0.5550, y = 0.5990,
})
local S = H.state
H.now = H.now + 86400
H.slash("start")
H.advance(10, function() S.x = S.x + 0.0005 end)
-- Shapeshift: the active power type changes.
S.powerType, S.powerToken, S.power, S.powerMax = 3, "ENERGY", 100, 100
H.advance(10, function() S.y = S.y + 0.0005 end)
-- Combat: health is a secret value and must be omitted, not zeroed.
S.hp, S.hpMax = SECRET, SECRET
S.power = 40
H.advance(10)
S.hp, S.hpMax = 290, 310
S.powerType, S.powerToken, S.power, S.powerMax = 0, "MANA", 380, 420
H.advance(10)
-- A merchant: an interaction with no quest.
S.npc = { name = "Mydrannul", guid = "Creature-0-3020-1-5-4241-00004C5D6E" }
H.fire("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", 5)
S.money = 1200
H.fire("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", 5)
S.npc = nil
H.advance(10)
H.reload()
H.slash("start")
H.advance(20, function() S.x = S.x - 0.0003 end)
H.slash("stop")
H.logout()
