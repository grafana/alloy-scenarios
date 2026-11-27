-- Alloy Route v2: records the logged-in character's session for later export.
-- The saved string uses ASCII delimiters and percent-encoded UTF-8 text, so
-- readers never need to evaluate Lua. companion/FORMAT.md documents every row.
local MAX_ROWS, MAX_BYTES = 4096, 1000000
local FOOTER_RESERVE = 32 -- ";e|<10-digit time>|<row count>" plus margin
local TICK_SECONDS = 10
local regions = { [1] = "us", [2] = "kr", [3] = "eu", [4] = "tw", [5] = "cn" }

local pending = {}     -- rows written this UI session, joined into the save at logout
local pendingBytes = 0 -- bytes those rows add to the saved string, separators included
local savedBytes, savedRows = 0, 0
local segment          -- the active recording segment, or nil
local timer, lastZone, lastBody, reminder, reloadHint = nil, nil, nil, 0, false
local full = false -- the last segment stopped because the next row did not fit
local openNpc, lastNpcKey, lastNpcAt = nil, nil, 0
local quests, recent = {}, {}
local interactionNames = {}

local function say(message)
    print("|cffe7c58bAlloy Route|r " .. message)
end

-- Restricted values are secret on this client; never compare or concatenate them.
local function readable(value)
    return not (issecretvalue and issecretvalue(value)) and value ~= nil
end

local function text(value)
    if not readable(value) or type(value) ~= "string" or value == "" then return "" end
    return (value:gsub("([^A-Za-z0-9_.%-])", function(byte)
        return string.format("%%%02X", string.byte(byte))
    end))
end

local function int(value)
    if not readable(value) or type(value) ~= "number" or value ~= value then return "" end
    return string.format("%.0f", value)
end

local function hasRecording()
    return savedRows > 0 or #pending > 0 or (AlloyRouteRecording ~= nil and AlloyRouteRecording ~= "")
end

local function usedBytes()
    return savedBytes + pendingBytes
end

local function usedRows()
    return savedRows + (segment and segment.count or 0)
end

-- Visible while this character has a recording to save or export.
local panel = CreateFrame("Frame", nil, UIParent)
panel:SetSize(292, 76)
panel:SetPoint("TOP", UIParent, "TOP", 0, -80)
local background = panel:CreateTexture(nil, "BACKGROUND")
background:SetAllPoints()
background:SetColorTexture(0.07, 0.09, 0.08, 0.91)
local title = panel:CreateFontString(nil, "OVERLAY", "GameFontNormal")
title:SetPoint("TOPLEFT", 10, -9)
local details = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
details:SetPoint("BOTTOMLEFT", 10, 10)
local save = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
save:SetSize(118, 24)
save:SetPoint("TOPRIGHT", -7, -5)
save:SetText("Save & Reload")
panel:Hide()

local function refreshPanel()
    local rows, bytes = usedRows(), usedBytes()
    local fraction = math.max(rows / MAX_ROWS, bytes / MAX_BYTES)
    local stage = 0
    if fraction >= 1 or full then
        stage = 3
    elseif fraction >= 0.8 then
        stage = 2
    elseif rows >= 500 or bytes >= 100000 then
        stage = 1
    end
    if stage > reminder then
        reminder = stage
        if stage == 3 then
            say("Recording full. Recording stopped. Click Save & Reload to write it to disk.")
        elseif stage == 2 then
            say("Recording is at least 80% full. Click Save & Reload when convenient.")
        else
            say("You have a sizeable recording. Click Save & Reload when convenient.")
        end
    end
    local state = timer and "Recording" or "Stopped"
    if stage == 3 then state = "Full" end
    title:SetText("Alloy Route - " .. state)
    local percent = math.min(100, math.floor(fraction * 100))
    local unit = rows == 1 and "row" or "rows"
    local usage = string.format("%d %s  ·  %.1f KiB  ·  %d%% full", rows, unit, bytes / 1024, percent)
    if reloadHint then usage = usage .. "\nType /reload to save if this panel stays open." end
    details:SetText(usage)
    if stage >= 2 then details:SetTextColor(1, 0.72, 0.25) else details:SetTextColor(1, 1, 1) end
    save:SetEnabled(#pending > 0)
    panel:Show()
end

-- Appends one row if it fits. Data rows count toward MAX_ROWS; every row
-- leaves room for the footer so a full recording can still be closed.
local function append(row, isData)
    local cost = #row + 1
    if isData and usedRows() + 1 > MAX_ROWS then return false end
    if usedBytes() + cost + FOOTER_RESERVE > MAX_BYTES then return false end
    pending[#pending + 1] = row
    pendingBytes = pendingBytes + cost
    return true
end

local finish

local function record(kind, ...)
    if not segment or segment.full then return false end
    segment.seq = segment.seq + 1
    local fields = { kind, int(GetServerTime()), int(segment.seq), ... }
    if not append(table.concat(fields, "|"), true) then
        segment.seq = segment.seq - 1
        segment.full, full = true, true
        finish()
        return false
    end
    segment.count = segment.count + 1
    refreshPanel()
    return true
end

local function place()
    local map = C_Map.GetBestMapForUnit("player")
    if not readable(map) then map = nil end
    local zone = GetRealZoneText()
    if not readable(zone) or zone == "" then zone = nil end
    local x, y
    if map then
        local position = C_Map.GetPlayerMapPosition(map, "player")
        if readable(position) and position then
            local px, py = position:GetXY()
            if readable(px) and readable(py) and px >= 0 and px <= 1 and py >= 0 and py <= 1 then
                -- Hundredths of a map percent, stored as locale-independent integers.
                x, y = math.floor(px * 10000 + 0.5), math.floor(py * 10000 + 0.5)
            end
        end
    end
    return map, zone, x, y
end

-- One measured snapshot. Unchanged ticks are skipped; forced snapshots are not.
local function snapshot(force, levelOverride)
    if not segment then return end
    local map, zone, x, y = place()
    local zoneKey = int(map) .. "|" .. text(zone)
    if (map or zone) and zoneKey ~= lastZone then
        if lastZone then record("z", int(map), text(zone)) end
        lastZone = zoneKey
        force = true
    end
    local powerType, powerToken = UnitPowerType("player")
    -- Addon code may not pass a secret value back into the API.
    if not readable(powerType) then powerType, powerToken = nil, nil end
    local level = levelOverride or UnitLevel("player")
    local body = table.concat({
        int(level), int(UnitXP("player")), int(UnitXPMax("player")),
        int(UnitHealth("player")), int(UnitHealthMax("player")),
        int(powerType), text(powerToken), int(UnitPower("player", powerType)),
        int(UnitPowerMax("player", powerType)), int(GetMoney()),
        int(map), text(zone), int(x), int(y),
    }, "|")
    if not force and body == lastBody then return end
    lastBody = body
    record("s", body)
end

finish = function()
    if not segment then return end
    if timer then
        timer:Cancel()
        timer = nil
    end
    -- The footer always fits: append() kept FOOTER_RESERVE bytes free.
    local footer = "e|" .. int(GetServerTime()) .. "|" .. segment.count
    pending[#pending + 1] = footer
    pendingBytes = pendingBytes + #footer + 1
    savedRows = savedRows + segment.count
    segment = nil
    refreshPanel()
end

local function commit()
    if #pending == 0 then return end
    local prior = AlloyRouteRecording
    if prior and prior ~= "" then
        AlloyRouteRecording = prior .. ";" .. table.concat(pending, ";")
    else
        AlloyRouteRecording = table.concat(pending, ";")
    end
    pending, pendingBytes = {}, 0
end

local function start()
    if segment then return say("Already recording.") end
    local saved = AlloyRouteRecording
    if saved and saved ~= "" and saved:sub(1, 3) ~= "v2|" then
        return say("This character has an older v1 route. Import it, then use /alloyroute clear.")
    end
    local name = UnitName("player")
    local region = regions[GetCurrentRegion()]
    local guid = UnitGUID("player")
    local realm = GetNormalizedRealmName and GetNormalizedRealmName() or nil
    if not readable(realm) or realm == "" then realm = GetRealmName() end
    if not readable(name) or name == "" or not region or not readable(guid) or not readable(realm) then
        return say("Character identity unavailable. Try again after entering the world.")
    end
    local now = GetServerTime()
    local version, build = GetBuildInfo()
    local _, raceFile, raceId = UnitRace("player")
    local _, classFile, classId = UnitClass("player")
    local faction = UnitFactionGroup("player")
    local id = string.format("%x%04x", now, math.random(0, 65535))
    local header = table.concat({
        "v2", id, int(now), text(version .. "." .. build), region, text(realm), text(name),
        text(guid), text(raceFile), int(raceId), text(classFile), int(classId), text(faction),
    }, "|")
    -- A new segment needs its header, a first snapshot and its footer.
    if usedRows() + 1 > MAX_ROWS or usedBytes() + #header + 1 + 400 + FOOTER_RESERVE > MAX_BYTES then
        return say("This character's recording is full. Export it, then use /alloyroute clear.")
    end
    append(header, false)
    segment = { id = id, seq = 0, count = 0 }
    lastZone, lastBody, reminder, reloadHint, full = nil, nil, 0, false, false
    snapshot(true)
    timer = C_Timer.NewTicker(TICK_SECONDS, function() snapshot(false) end)
    refreshPanel()
    if savedRows > 0 then
        say("Recording a new session after the saved ones. Click Save & Reload when finished.")
    else
        say("Recording this character. Click Save & Reload when finished.")
    end
end

save:SetScript("OnClick", function()
    snapshot(true)
    reloadHint = true
    refreshPanel()
    -- PLAYER_LOGOUT finalizes the segment when the client actually reloads.
    -- A denied click leaves an active recording running.
    if not (C_UI and C_UI.Reload and pcall(C_UI.Reload)) then
        say("Type /reload to save your recording.")
    end
end)

-- Interactions ---------------------------------------------------------------

local function npcIdentity()
    if not UnitExists("npc") then return "", "", "" end
    local guid, name = UnitGUID("npc"), UnitName("npc")
    local unitType, npcId = "", ""
    if readable(guid) then
        local kind, _, _, _, _, id = strsplit("-", guid)
        if kind == "Player" then return "Player", "", "" end
        unitType, npcId = text(kind), int(tonumber(id))
    end
    return unitType, npcId, text(name)
end

-- Several UI events describe the same NPC window; keep the first for each opening.
local function noteNpc(kind)
    if not segment then return end
    local unitType, npcId, name = npcIdentity()
    if unitType == "Player" then return end
    local key = unitType .. npcId .. name
    if key == "" then key = kind end
    local now = GetTime()
    if key == openNpc or (key == lastNpcKey and now - lastNpcAt < 5) then return end
    openNpc, lastNpcKey, lastNpcAt = key, key, now
    record("n", text(kind), unitType, npcId, name)
end

local function rememberQuest()
    local id = GetQuestID and GetQuestID()
    if not readable(id) or not id or id == 0 then return end
    local unitType, npcId, name = npcIdentity()
    quests[id] = { title = GetTitleText and GetTitleText(), unitType = unitType, npcId = npcId, name = name }
end

local function quest(kind, id, xpReward, moneyReward)
    if not segment or not readable(id) or type(id) ~= "number" then return end
    local key = kind .. id
    local now = GetTime()
    if recent[key] and now - recent[key] < 10 then return end
    recent[key] = now
    local cached = quests[id] or {}
    local questTitle = C_QuestLog and C_QuestLog.GetTitleForQuestID and C_QuestLog.GetTitleForQuestID(id)
    if not readable(questTitle) or questTitle == "" then questTitle = cached.title end
    record("q", kind, int(id), text(questTitle), int(xpReward), int(moneyReward),
        cached.unitType or "", cached.npcId or "", cached.name or "")
end

SLASH_ALLOYROUTE1 = "/alloyroute"
SlashCmdList.ALLOYROUTE = function(input)
    local cmd = strtrim(input):lower()
    if cmd == "start" then
        start()
    elseif cmd == "stop" and segment then
        snapshot(true)
        finish()
        say("Stopped. Click Save & Reload or log out to write your recording to disk.")
    elseif cmd == "clear" and not segment then
        if hasRecording() then
            say("This deletes the saved recording. Export it first, then type /alloyroute clear confirm.")
        else
            say("Nothing to clear.")
        end
    elseif cmd == "clear confirm" and not segment then
        AlloyRouteRecording, pending, pendingBytes, savedBytes, savedRows = nil, {}, 0, 0, 0
        panel:Hide()
        say("Cleared this character's saved recording.")
    elseif cmd == "status" then
        say(string.format("%s. %d rows, %.1f KiB of %d KiB.", segment and "Recording" or "Stopped",
            usedRows(), usedBytes() / 1024, MAX_BYTES / 1024))
    else
        say((segment and "Recording. " or "") .. "Commands: /alloyroute start, stop, status, clear.")
    end
end

local events = CreateFrame("Frame")
for _, name in ipairs({
    "ADDON_LOADED", "PLAYER_LOGOUT", "PLAYER_ENTERING_WORLD", "ZONE_CHANGED_NEW_AREA",
    "PLAYER_LEVEL_UP", "PLAYER_INTERACTION_MANAGER_FRAME_SHOW", "PLAYER_INTERACTION_MANAGER_FRAME_HIDE",
    "GOSSIP_SHOW", "GOSSIP_CLOSED", "QUEST_GREETING", "QUEST_DETAIL", "QUEST_PROGRESS",
    "QUEST_COMPLETE", "QUEST_FINISHED", "QUEST_ACCEPTED", "QUEST_TURNED_IN",
}) do
    events:RegisterEvent(name)
end

events:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        if ... ~= "AlloyRoute" then return end
        local saved = AlloyRouteRecording
        if type(saved) ~= "string" then AlloyRouteRecording, saved = nil, "" end
        savedBytes = #saved
        for row in saved:gmatch("[^;]+") do
            local kind = row:sub(1, 2)
            if kind ~= "v1" and kind ~= "v2" and kind ~= "e|" then
                savedRows = savedRows + 1
            end
        end
        if Enum and Enum.PlayerInteractionType then
            for key, value in pairs(Enum.PlayerInteractionType) do interactionNames[value] = key end
        end
        if savedBytes > 0 then
            reminder = 3 -- capacity warnings are for the session being recorded
            refreshPanel()
            say(string.format("%d saved rows are waiting for export. Read the file, then /alloyroute clear.",
                savedRows))
        end
        return
    elseif event == "PLAYER_LOGOUT" then
        if segment then
            snapshot(false)
            finish()
        end
        commit()
        return
    end
    if not segment then return end
    if event == "PLAYER_ENTERING_WORLD" or event == "ZONE_CHANGED_NEW_AREA" then
        snapshot(false)
    elseif event == "PLAYER_LEVEL_UP" then
        local level = ...
        record("l", int(level))
        -- UnitLevel and UnitXPMax can lag the event; take a second look shortly after.
        snapshot(true, level)
        C_Timer.After(2, function() snapshot(false) end)
    elseif event == "PLAYER_INTERACTION_MANAGER_FRAME_SHOW" then
        local kind = interactionNames[...]
        if kind and kind ~= "None" and kind ~= "TradePartner" then noteNpc(kind) end
    elseif event == "GOSSIP_SHOW" then
        noteNpc("Gossip")
    elseif event == "QUEST_GREETING" or event == "QUEST_PROGRESS" then
        noteNpc("QuestGiver")
    elseif event == "QUEST_DETAIL" or event == "QUEST_COMPLETE" then
        noteNpc("QuestGiver")
        rememberQuest()
    elseif event == "QUEST_ACCEPTED" then
        quest("accepted", (...))
    elseif event == "QUEST_TURNED_IN" then
        quest("turned_in", ...)
    elseif event == "PLAYER_INTERACTION_MANAGER_FRAME_HIDE" or event == "QUEST_FINISHED" then
        openNpc = nil
    elseif event == "GOSSIP_CLOSED" then
        if not ... then openNpc = nil end
    end
end)
