-- Offline WoW API stand-in for AlloyRoute.lua. Run with Lua 5.1, WoW's dialect:
--   lua5.1 harness.lua <AlloyRoute.lua> <scenario.lua> <SavedVariables output>
-- The scenario drives a fake character through `H` and the harness writes the
-- per-character SavedVariables file the way the client does at logout.
local addonPath, scenarioPath, outputPath = arg[1], arg[2], arg[3]
-- Deterministic across Lua builds, so the committed fixtures stay reproducible.
local draws = 0
math.random = function(low, high)
    draws = draws + 1
    return low + (draws * 40503) % (high - low + 1)
end
unpack = unpack or table.unpack -- WoW and LuaJIT are Lua 5.1

SECRET = setmetatable({}, { __tostring = function() return "<secret>" end })
H = { now = 1790000000, uptime = 1000, messages = {}, state = {}, frames = {}, timers = {} }
local S = H.state

function issecretvalue(value) return value == SECRET end
function print(...) table.insert(H.messages, table.concat({ ... }, " ")) end
function strtrim(value) return (value:gsub("^%s+", ""):gsub("%s+$", "")) end
function strsplit(sep, value)
    local parts = {}
    for piece in (value .. sep):gmatch("(.-)" .. sep:gsub("%p", "%%%0")) do parts[#parts + 1] = piece end
    return unpack(parts)
end

local widget = {}
widget.__index = function(_, key)
    return widget[key] or function() end
end
function widget:SetScript(name, fn) self.scripts[name] = fn end
function widget:RegisterEvent(name) self.events[name] = true end
function widget:Show() self.shown = true end
function widget:Hide() self.shown = false end
function widget:SetText(value) self.text = value end
function widget:SetEnabled(value) self.enabled = value end
local function newWidget()
    return setmetatable({ scripts = {}, events = {} }, widget)
end
function widget:CreateTexture() return newWidget() end
function widget:CreateFontString() return newWidget() end
function CreateFrame()
    local frame = newWidget()
    table.insert(H.frames, frame)
    return frame
end
UIParent = newWidget()

C_Timer = {}
function C_Timer.NewTicker(seconds, fn)
    local ticker = { every = seconds, due = H.now + seconds, fn = fn }
    function ticker:Cancel() self.cancelled = true end
    table.insert(H.timers, ticker)
    return ticker
end
function C_Timer.After(seconds, fn)
    table.insert(H.timers, { due = H.now + seconds, fn = fn, once = true })
end

function GetServerTime() return H.now end
function GetTime() return H.uptime end
function GetBuildInfo() return "1.60.1", "71139", "Nov 13 2026", 16001 end
function GetCurrentRegion() return S.regionId end
function GetNormalizedRealmName() return S.realm end
function GetRealmName() return S.realm end
function GetRealZoneText() return S.zone or "" end
function GetMoney() return S.money end
function UnitName(unit)
    if unit == "npc" then return S.npc and S.npc.name end
    return S.name
end
function UnitGUID(unit)
    if unit == "npc" then return S.npc and S.npc.guid end
    return S.guid
end
function UnitExists(unit) return unit == "npc" and S.npc ~= nil end
function UnitRace() return S.raceName, S.raceFile, S.raceId end
function UnitClass() return S.className, S.classFile, S.classId end
function UnitFactionGroup() return S.faction, S.faction end
function UnitLevel() return S.level end
function UnitXP() return S.xp end
function UnitXPMax() return S.xpMax end
function UnitHealth() return S.hp end
function UnitHealthMax() return S.hpMax end
function UnitPowerType() return S.powerType, S.powerToken end
function UnitPower() return S.power end
function UnitPowerMax() return S.powerMax end
function GetQuestID() return S.window and S.window.id or 0 end
function GetTitleText() return S.window and S.window.title end
C_QuestLog = { GetTitleForQuestID = function(id) return S.questLog and S.questLog[id] end }
C_Map = {
    GetBestMapForUnit = function() return S.map end,
    GetPlayerMapPosition = function()
        if S.x == nil then return nil end
        return { GetXY = function() return S.x, S.y end }
    end,
}
C_UI = { Reload = function() H.reloadRequested = true end }
Enum = { PlayerInteractionType = { None = 0, TradePartner = 1, Gossip = 3, QuestGiver = 4, Merchant = 5, Trainer = 7 } }
SlashCmdList = {}

function H.fire(event, ...)
    for _, frame in ipairs(H.frames) do
        if frame.events[event] and frame.scripts.OnEvent then frame.scripts.OnEvent(frame, event, ...) end
    end
end

function H.slash(command) SlashCmdList.ALLOYROUTE(command) end

-- Advance the clock one second at a time, running due timers.
function H.advance(seconds, each)
    for _ = 1, seconds do
        H.now, H.uptime = H.now + 1, H.uptime + 1
        if each then each() end
        for _, timer in ipairs(H.timers) do
            if not timer.cancelled and not timer.spent and timer.due <= H.now then
                if timer.once then timer.spent = true else timer.due = timer.due + timer.every end
                timer.fn()
            end
        end
    end
end

-- Load the addon as the client does: fresh code, then saved variables, then ADDON_LOADED.
function H.load()
    H.frames, H.timers, SlashCmdList = {}, {}, {}
    dofile(addonPath)
    H.fire("ADDON_LOADED", "AlloyRoute")
end

function H.click()
    for _, frame in ipairs(H.frames) do
        if frame.scripts.OnClick then frame.scripts.OnClick(frame) end
    end
end

-- Save & Reload or /reload: PLAYER_LOGOUT, write saved variables, load again.
function H.reload()
    H.fire("PLAYER_LOGOUT")
    H.saved = AlloyRouteRecording
    H.advance(5)
    AlloyRouteRecording = H.saved
    H.load()
    H.fire("PLAYER_ENTERING_WORLD", false, true)
end

function H.logout()
    H.fire("PLAYER_LOGOUT")
    H.saved = AlloyRouteRecording
end

function H.character(values)
    for key in pairs(S) do S[key] = nil end
    for key, value in pairs(values) do S[key] = value end
end

H.load()
dofile(scenarioPath)

local out = assert(io.open(outputPath, "w"))
if H.saved ~= nil then
    out:write("\nAlloyRouteRecording = ", string.format("%q", H.saved), "\n")
else
    out:write("\nAlloyRouteRecording = nil\n")
end
out:close()
local messages = assert(io.open(outputPath .. ".messages", "w"))
messages:write(table.concat(H.messages, "\n"), "\n")
messages:close()
