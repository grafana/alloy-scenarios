-- The saved string uses ASCII delimiters and percent-encoded UTF-8 names.
-- This lets the web app read a single variable without interpreting Lua.
local timer, lastPoint, pointCount
local MAX_POINTS, MAX_BYTES = 4096, 1000000
local reminder, reloadHint = 0, false
local regions = { [1] = "us", [2] = "kr", [3] = "eu", [4] = "tw", [5] = "cn" }
local function say(message)
    print("|cffe7c58bAlloy Route|r " .. message)
end

local function readable(value)
    return not (issecretvalue and issecretvalue(value))
end

local function encode(value)
    return (value:gsub("([^A-Za-z0-9_.%-])", function(byte)
        return string.format("%%%02X", string.byte(byte))
    end))
end

-- Visible only while this UI session has a route to save.
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
    local bytes = #AlloyRouteRecording
    local fraction = math.max(pointCount / MAX_POINTS, bytes / MAX_BYTES)
    local stage = 0
    if fraction >= 1 then
        stage = 3
    elseif fraction >= 0.8 then
        stage = 2
    elseif pointCount >= 500 or bytes >= 100000 then
        stage = 1
    end
    if stage > reminder then
        reminder = stage
        if stage == 3 then
            say("Route full. Recording stopped. Click Save & Reload to write it to disk.")
        elseif stage == 2 then
            say("Route is at least 80% full. Click Save & Reload when convenient.")
        else
            say("You have a sizeable route recorded. Click Save & Reload when convenient.")
        end
    end
    local state = timer and "Recording" or "Stopped"
    if stage == 3 then state = "Full" end
    title:SetText("Alloy Route - " .. state)
    local percent = math.min(100, math.floor(fraction * 100))
    local unit = pointCount == 1 and "waypoint" or "waypoints"
    local usage = string.format("%d %s  ·  %.1f KiB  ·  %d%% full", pointCount, unit, bytes / 1024, percent)
    if reloadHint then usage = usage .. "\nType /reload to save if this panel stays open." end
    details:SetText(usage)
    if stage >= 2 then details:SetTextColor(1, 0.72, 0.25) else details:SetTextColor(1, 1, 1) end
    save:SetEnabled(pointCount > 0)
    panel:Show()
end

local function finish()
    if timer then
        timer:Cancel()
        timer = nil
        AlloyRouteRecording = AlloyRouteRecording .. ";end|" .. GetServerTime()
        refreshPanel()
    end
end

local function sample()
    local zone = GetRealZoneText()
    if not readable(zone) or not zone or zone == "" then return end
    local map = C_Map.GetBestMapForUnit("player")
    if not readable(map) then map = nil end
    local xy = "|"
    if map then
        local position = C_Map.GetPlayerMapPosition(map, "player")
        if readable(position) and position then
            local x, y = position:GetXY()
            if readable(x) and readable(y) and x and y and x >= 0 and x <= 1 and y >= 0 and y <= 1 then
                -- Hundredths of a map percent, stored as locale-independent integers.
                xy = math.floor(x * 10000 + 0.5) .. "|" .. math.floor(y * 10000 + 0.5)
            end
        end
    end
    local point = (map or 0) .. "|" .. encode(zone) .. "|" .. xy
    if point == lastPoint then return end
    AlloyRouteRecording = AlloyRouteRecording .. ";" .. GetServerTime() .. "|" .. point
    pointCount = pointCount + 1
    lastPoint = point
    if pointCount >= MAX_POINTS or #AlloyRouteRecording >= MAX_BYTES then
        finish()
    else
        refreshPanel()
    end
end

save:SetScript("OnClick", function()
    if timer then sample() end
    reloadHint = true
    refreshPanel()
    -- PLAYER_LOGOUT finalizes the route when the client actually reloads.
    -- A denied click leaves an active recording running.
    if not (C_UI and C_UI.Reload and pcall(C_UI.Reload)) then
        say("Type /reload to save your route.")
    end
end)

local function start()
    if timer then return say("Already recording.") end
    if AlloyRouteRecording then return say("Import the saved route, then use /alloyroute clear before starting another.") end
    local name = GetUnitName("player", false)
    local region = regions[GetCurrentRegion()]
    if not readable(name) or not name or name == "" or not region then
        return say("Character identity unavailable. Try again after entering the world.")
    end
    AlloyRouteRecording = "v1|" .. region .. "|" .. encode(name) .. "|" .. GetServerTime()
    pointCount, lastPoint, reminder, reloadHint = 0, nil, 0, false
    timer = C_Timer.NewTicker(10, sample)
    refreshPanel()
    sample()
    say("Recording your route. Click Save & Reload when finished.")
end

SLASH_ALLOYROUTE1 = "/alloyroute"
SlashCmdList.ALLOYROUTE = function(input)
    local cmd = strtrim(input):lower()
    if cmd == "start" then
        start()
    elseif cmd == "stop" and timer then
        sample()
        finish()
        say("Stopped. Click Save & Reload or log out to write your route to disk.")
    elseif cmd == "clear" and not timer then
        AlloyRouteRecording = nil
        panel:Hide()
        say("Cleared this character's saved route.")
    else
        say((timer and "Recording. " or "") .. "Commands: /alloyroute start, stop, clear.")
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("ZONE_CHANGED_NEW_AREA")
events:RegisterEvent("PLAYER_LOGOUT")
events:SetScript("OnEvent", function(_, event)
    if not timer then return end
    if event == "PLAYER_LOGOUT" then finish() else sample() end
end)
