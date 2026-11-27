-- Fixture A: Undead warrior "Morrow" on Stonewake (EU), starting in Tirisfal Glades.
-- Rage (a non-mana resource) at a legitimate zero, zero copper, a stationary XP
-- gain, an NPC with gossip and a quest window, an accept, a turn-in with
-- rewards, a level-up, and an instance zone with no map position.
H.character({
    regionId = 3, realm = "Stonewake", name = "Morrow", guid = "Player-1001-0A1B2C3D",
    raceName = "Undead", raceFile = "Scourge", raceId = 5, className = "Warrior",
    classFile = "WARRIOR", classId = 1, faction = "Horde",
    level = 4, xp = 900, xpMax = 1100, hp = 120, hpMax = 120,
    powerType = 1, powerToken = "RAGE", power = 0, powerMax = 100, money = 0,
    map = 1420, zone = "Tirisfal Glades", x = 0.3012, y = 0.7120,
})
local S = H.state
H.slash("start")
H.advance(10, function() S.x = S.x + 0.0004 end)
H.advance(10, function() S.y = S.y - 0.0004 end)
-- Standing still while a party kill grants XP.
H.advance(5)
S.xp = 960
H.advance(5)
-- Gossip NPC that offers a quest. Several UI events describe one opening.
S.npc = { name = "Executor Arren", guid = "Creature-0-4170-0-12-1570-000012A3B4" }
H.fire("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", 3)
H.fire("GOSSIP_SHOW", nil)
H.fire("GOSSIP_CLOSED", true)
S.window = { id = 364, title = "The Mindless Ones" }
H.fire("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", 4)
H.fire("QUEST_DETAIL", nil)
S.questLog = { [364] = "The Mindless Ones" }
H.fire("QUEST_ACCEPTED", 364)
H.fire("QUEST_ACCEPTED", 364)
H.fire("QUEST_FINISHED")
H.fire("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", 4)
S.npc, S.window = nil, nil
H.advance(40, function() S.x = S.x + 0.0002; S.power = 12 end)
-- Turn in: the reward stays separate from the measured XP and copper.
S.npc = { name = "Executor Arren", guid = "Creature-0-4170-0-12-1570-000012A3B4" }
S.window = { id = 364, title = "The Mindless Ones" }
H.fire("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", 4)
H.fire("QUEST_COMPLETE")
S.questLog = {}
S.xp, S.money = 1250, 35
H.fire("QUEST_TURNED_IN", 364, 250, 35)
-- XP crossed the level. UnitLevel lags the event on the live client.
S.xp, S.xpMax = 150, 1400
H.fire("PLAYER_LEVEL_UP", 5, 18, 0, 0, 1, 0, 0, 0, 0)
S.level, S.hpMax, S.hp = 5, 138, 138
H.fire("QUEST_FINISHED")
S.npc, S.window = nil, nil
H.advance(10)
-- A dungeon: zone changes, coordinates are unavailable.
S.map, S.zone, S.x, S.y = 279, "The Deadmines", nil, nil
H.fire("ZONE_CHANGED_NEW_AREA")
H.advance(20, function() S.hp = S.hp - 2 end)
S.map, S.zone, S.x, S.y = 1420, "Tirisfal Glades", 0.3100, 0.7000
H.fire("ZONE_CHANGED_NEW_AREA")
H.advance(10)
H.click()
H.reload()
