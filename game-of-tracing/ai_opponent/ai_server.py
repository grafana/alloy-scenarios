import os
import time
import random
import requests
import threading
import atexit
from flask import Flask, jsonify, request
from telemetry import AITelemetry
from opentelemetry import trace, baggage
from opentelemetry.trace import SpanKind
from opentelemetry.propagate import inject
from datetime import datetime, timedelta
from enum import Enum

app = Flask(__name__)

# Initialize telemetry
telemetry = AITelemetry()
logger = telemetry.get_logger()
tracer = telemetry.get_tracer()
atexit.register(telemetry.shutdown)

# AI Configuration
class GamePhase(Enum):
    EARLY = "early"  # First 5 minutes
    MID = "mid"      # 5-15 minutes
    LATE = "late"    # After 15 minutes

class AIState:
    def __init__(self):
        self.faction = None
        self.active = False
        self.last_action_time = None
        self.game_start_time = None
        self.recent_player_actions = []  # Track recent player moves
        self.decision_thread = None
        self.stop_flag = threading.Event()

ai_state = AIState()

# Location configuration (matches game_config.py)
LOCATION_PORTS = {
    "southern_capital": 5001,
    "northern_capital": 5002,
    "village_1": 5003,
    "village_2": 5004,
    "village_3": 5005,
    "village_4": 5006,
    "village_5": 5007,
    "village_6": 5008
}

# AI Decision weights for different game phases
DECISION_WEIGHTS = {
    GamePhase.EARLY: {
        "collect_resources": 40,
        "capture_neutral": 35,
        "create_army": 20,
        "defensive_move": 5,
        "offensive_move": 0
    },
    GamePhase.MID: {
        "collect_resources": 25,
        "capture_neutral": 20,
        "create_army": 25,
        "defensive_move": 15,
        "offensive_move": 15
    },
    GamePhase.LATE: {
        "collect_resources": 15,
        "capture_neutral": 10,
        "create_army": 20,
        "defensive_move": 20,
        "offensive_move": 35
    }
}

def get_location_url(location_id):
    """Get the URL for a location's API"""
    if os.environ.get('IN_DOCKER'):
        host = location_id.replace('_', '-')
    else:
        host = 'localhost'
    
    port = LOCATION_PORTS[location_id]
    return f"http://{host}:{port}"

def make_api_request(location_id, endpoint, method='GET', data=None):
    """Make an API request to a location server with trace context"""
    url = f"{get_location_url(location_id)}/{endpoint}"
    headers = {"Content-Type": "application/json"}
    
    with tracer.start_as_current_span(
        "ai_api_request",
        kind=SpanKind.CLIENT,
        attributes={
            "location.id": location_id,
            "location.endpoint": endpoint,
            "http.method": method
        }
    ) as span:
        inject(headers)  # Inject trace context
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            else:  # POST
                response = requests.post(url, json=data, headers=headers)
            
            span.set_attribute("http.status_code", response.status_code)
            response.raise_for_status()
            result = response.json()
            
            if not result.get("success", True):
                span.set_status(trace.StatusCode.ERROR, result.get("message", "Unknown error"))
            
            return result
        except requests.RequestException as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            logger.error(f"API request failed: {str(e)}")
            return {"error": str(e)}

def get_game_state(parent_ctx):
    """Get the current state of all locations"""
    with tracer.start_as_current_span(
        "get_game_state",
        kind=SpanKind.INTERNAL,
        context=parent_ctx,
        attributes={"location_count": len(LOCATION_PORTS)}
    ) as span:
        game_state = {}
        error_count = 0
        
        for location_id in LOCATION_PORTS.keys():
            data = make_api_request(location_id, '')
            if 'error' not in data:
                game_state[location_id] = data
            else:
                error_count += 1
                span.add_event(
                    "location_fetch_error",
                    attributes={
                        "location": location_id,
                        "error": str(data.get('error', 'Unknown error'))
                    }
                )
        
        span.set_attribute("locations_retrieved", len(game_state))
        span.set_attribute("errors", error_count)
        
        if error_count > 0:
            span.set_status(trace.StatusCode.ERROR, f"Failed to fetch {error_count} locations")
        
        return game_state

def get_game_phase():
    """Determine the current game phase based on elapsed time"""
    if not ai_state.game_start_time:
        return GamePhase.EARLY
    
    elapsed = (datetime.now() - ai_state.game_start_time).total_seconds() / 60
    
    if elapsed < 5:
        return GamePhase.EARLY
    elif elapsed < 15:
        return GamePhase.MID
    else:
        return GamePhase.LATE

def analyze_threats(game_state):
    """Analyze potential threats to AI territories"""
    threats = []
    my_capital = "southern_capital" if ai_state.faction == "southern" else "northern_capital"
    
    for loc_id, loc_data in game_state.items():
        if loc_data['faction'] == ai_state.faction:
            # Check neighboring locations for enemy armies
            for connection in loc_data['connections']:
                neighbor = game_state.get(connection)
                if neighbor and neighbor['faction'] != ai_state.faction and neighbor['army'] > 0:
                    threat_level = neighbor['army'] - loc_data['army']
                    # Calculate distance to capital for threat prioritization
                    distance_to_capital = 1 if loc_id == my_capital else 2
                    
                    threats.append({
                        'location': loc_id,
                        'threat_from': connection,
                        'threat_level': threat_level,
                        'enemy_army_size': neighbor['army'],
                        'defending_army_size': loc_data['army'],
                        'is_capital': loc_id == my_capital,
                        'distance_to_capital': distance_to_capital
                    })
    
    # Check for armies that could reach the capital in one move
    capital_neighbors = game_state[my_capital]['connections']
    for neighbor_id in capital_neighbors:
        neighbor = game_state.get(neighbor_id)
        if neighbor and neighbor['faction'] != ai_state.faction and neighbor['army'] > 0:
            # This is a direct threat to the capital
            for threat in threats:
                if threat['threat_from'] == neighbor_id and threat['is_capital']:
                    threat['imminent_capital_threat'] = True
                    threat['threat_urgency'] = 'critical'
    
    return sorted(threats, key=lambda x: (x.get('imminent_capital_threat', False), x['is_capital'], x['threat_level']), reverse=True)

def find_expansion_targets(game_state):
    """Find neutral villages or weak enemy territories to capture"""
    targets = []
    
    for loc_id, loc_data in game_state.items():
        if loc_data['faction'] != ai_state.faction:
            # Find AI territories that can reach this location
            for connection in loc_data['connections']:
                neighbor = game_state.get(connection)
                if neighbor and neighbor['faction'] == ai_state.faction and neighbor['army'] > 0:
                    # Calculate attack potential
                    advantage = neighbor['army'] - loc_data['army']
                    targets.append({
                        'target': loc_id,
                        'from': connection,
                        'advantage': advantage,
                        'is_neutral': loc_data['faction'] == 'neutral',
                        'is_capital': 'capital' in loc_id
                    })
    
    # Sort by neutrals first, then by advantage
    return sorted(targets, key=lambda x: (not x['is_neutral'], -x['advantage']))

def make_decision(game_state, parent_ctx):
    """Make a strategic decision based on game state"""
    with tracer.start_as_current_span(
        "ai_decision",
        kind=SpanKind.INTERNAL,
        context=parent_ctx,
        attributes={"game_phase": get_game_phase().value}
    ) as span:
        phase = get_game_phase()
        weights = DECISION_WEIGHTS[phase]
        
        # Analyze the current situation
        threats = analyze_threats(game_state)
        targets = find_expansion_targets(game_state)
        my_capital = "southern_capital" if ai_state.faction == "southern" else "northern_capital"
        capital_state = game_state[my_capital]
        
        span.set_attribute("threats_count", len(threats))
        span.set_attribute("targets_count", len(targets))
        span.set_attribute("capital_resources", capital_state['resources'])
        
        # Check for imminent capital threat
        imminent_capital_threat = False
        threat_army_size = 0
        for threat in threats:
            if threat.get('imminent_capital_threat', False):
                imminent_capital_threat = True
                threat_army_size = threat['enemy_army_size']
                span.set_attribute("imminent_capital_threat", True)
                span.set_attribute("threat_army_size", threat_army_size)
                logger.warning(f"IMMINENT CAPITAL THREAT DETECTED! Enemy army size: {threat_army_size}")
                break
        
        # If capital is under imminent threat and we have resources, create armies immediately
        if imminent_capital_threat and capital_state['resources'] >= 30:
            # Check if we already have enough armies to defend
            current_defense = capital_state['army']
            
            # Only create armies if we don't have enough to defend (with a small buffer)
            defense_buffer = 2  # We want at least 2 more armies than the threat
            needed_defense = threat_army_size + defense_buffer
            
            if current_defense < needed_defense:
                # Calculate how many armies we can create
                armies_we_can_create = capital_state['resources'] // 30
                armies_needed = min(armies_we_can_create, needed_defense - current_defense)
                
                span.set_attribute("defense_calculation", {
                    "current_army": capital_state['army'],
                    "threat_size": threat_army_size,
                    "needed_defense": needed_defense,
                    "can_create": armies_we_can_create,
                    "will_create": armies_needed
                })
                
                logger.info(f"Capital defense: current={current_defense}, threat={threat_army_size}, needed={needed_defense}, will_create={armies_needed}")
                
                # Create armies for defense
                return {
                    'action': 'create_army',
                    'threats': threats,
                    'targets': targets,
                    'game_state': game_state,
                    'emergency_defense': True,
                    'armies_to_create': armies_needed
                }
            else:
                logger.info(f"Capital has sufficient defense: {current_defense} armies vs threat of {threat_army_size}")
                span.set_attribute("sufficient_defense", True)
                # Continue with normal decision making
        
        # Adjust weights based on situation
        adjusted_weights = weights.copy()
        
        # If under immediate threat, prioritize defense
        if threats and threats[0]['threat_level'] > 2:
            adjusted_weights['defensive_move'] += 30
            adjusted_weights['offensive_move'] = max(0, adjusted_weights['offensive_move'] - 20)
        
        # If we have high resources, prioritize army creation
        if capital_state['resources'] > 100:
            adjusted_weights['create_army'] += 20
        
        # If no neutral villages left, reduce capture weight
        neutral_targets = [t for t in targets if t['is_neutral']]
        if not neutral_targets:
            adjusted_weights['capture_neutral'] = 0
        
        # Make weighted random choice
        actions = list(adjusted_weights.keys())
        weights_list = list(adjusted_weights.values())
        
        # Remove actions with 0 weight
        actions = [a for a, w in zip(actions, weights_list) if w > 0]
        weights_list = [w for w in weights_list if w > 0]
        
        if not actions:
            return None
        
        chosen_action = random.choices(actions, weights=weights_list)[0]
        span.set_attribute("chosen_action", chosen_action)
        
        return {
            'action': chosen_action,
            'threats': threats,
            'targets': targets,
            'game_state': game_state
        }

def execute_action(decision, parent_ctx):
    """Execute the chosen action"""
    if not decision:
        return
    
    action = decision['action']
    game_state = decision['game_state']
    
    with tracer.start_as_current_span(
        "execute_ai_action",
        kind=SpanKind.INTERNAL,
        context=parent_ctx,
        attributes={"action_type": action}
    ) as span:
        try:
            if action == "collect_resources":
                my_capital = "southern_capital" if ai_state.faction == "southern" else "northern_capital"
                result = make_api_request(my_capital, 'collect_resources', method='POST')
                logger.info(f"AI collected resources: {result}")
                
            elif action == "create_army":
                my_capital = "southern_capital" if ai_state.faction == "southern" else "northern_capital"
                capital_state = game_state[my_capital]
                
                # Check if this is emergency defense mode
                if decision.get('emergency_defense', False):
                    span.set_attribute("emergency_defense", True)
                    armies_created = 0
                    armies_to_create = decision.get('armies_to_create', 1)  # Default to 1 if not specified
                    
                    # Create only the needed number of armies
                    while armies_created < armies_to_create and capital_state['resources'] >= 30:
                        result = make_api_request(my_capital, 'create_army', method='POST')
                        if result.get('success'):
                            armies_created += 1
                            capital_state['resources'] = result.get('current_resources', capital_state['resources'] - 30)
                            capital_state['army'] = result.get('current_army', capital_state['army'] + 1)
                            logger.info(f"AI created emergency defense army #{armies_created}/{armies_to_create}: {result}")
                        else:
                            logger.warning(f"Failed to create emergency army: {result}")
                            break
                        
                        # Brief pause between army creations
                        time.sleep(0.5)
                    
                    span.set_attribute("armies_created", armies_created)
                    span.set_attribute("armies_requested", armies_to_create)
                    logger.info(f"AI created {armies_created}/{armies_to_create} armies for emergency capital defense")
                else:
                    # Normal army creation
                    if capital_state['resources'] >= 30:
                        result = make_api_request(my_capital, 'create_army', method='POST')
                        logger.info(f"AI created army: {result}")
                
            elif action == "capture_neutral":
                targets = [t for t in decision['targets'] if t['is_neutral'] and t['advantage'] >= 0]
                if targets:
                    target = targets[0]
                    result = make_api_request(
                        target['from'], 
                        'move_army', 
                        method='POST',
                        data={"target_location": target['target']}
                    )
                    logger.info(f"AI capturing neutral village: {target['target']}")
                    span.set_attribute("target_location", target['target'])
                
            elif action == "defensive_move":
                threats = decision['threats']
                if threats:
                    threat = threats[0]
                    # Find reinforcements
                    for loc_id, loc_data in game_state.items():
                        if (loc_data['faction'] == ai_state.faction and 
                            loc_data['army'] > 0 and 
                            loc_id != threat['location'] and
                            threat['location'] in loc_data['connections']):
                            result = make_api_request(
                                loc_id,
                                'move_army',
                                method='POST',
                                data={"target_location": threat['location']}
                            )
                            logger.info(f"AI reinforcing {threat['location']} from {loc_id}")
                            span.set_attribute("reinforced_location", threat['location'])
                            break
                
            elif action == "offensive_move":
                targets = [t for t in decision['targets'] if not t['is_neutral'] and t['advantage'] > 0]
                if targets:
                    # Occasionally launch all-out attack in late game
                    if get_game_phase() == GamePhase.LATE and random.random() < 0.3:
                        my_capital = "southern_capital" if ai_state.faction == "southern" else "northern_capital"
                        capital_state = game_state[my_capital]
                        if capital_state['army'] >= 5:
                            result = make_api_request(my_capital, 'all_out_attack', method='POST')
                            logger.info("AI launching all-out attack!")
                            span.set_attribute("all_out_attack", True)
                    else:
                        target = targets[0]
                        result = make_api_request(
                            target['from'],
                            'move_army',
                            method='POST',
                            data={"target_location": target['target']}
                        )
                        logger.info(f"AI attacking {target['target']} from {target['from']}")
                        span.set_attribute("attack_target", target['target'])
            
            # Also handle resource transfers from villages
            if random.random() < 0.3:  # 30% chance each turn
                for loc_id, loc_data in game_state.items():
                    if (loc_data['faction'] == ai_state.faction and 
                        'village' in loc_id and 
                        loc_data['resources'] > 50):
                        result = make_api_request(loc_id, 'send_resources_to_capital', method='POST')
                        logger.info(f"AI sending resources from {loc_id} to capital")
                        break
                        
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            logger.error(f"Error executing AI action: {str(e)}")

def ai_decision_loop():
    """Main AI decision loop that runs in a separate thread"""
    logger.info(f"AI decision loop started for {ai_state.faction} faction")
    
    decision_count = 0
    
    while ai_state.active and not ai_state.stop_flag.is_set():
        decision_count += 1
        
            # Create a root span for each complete decision cycle
        with tracer.start_as_current_span(
                "ai_decision_cycle",
                kind=SpanKind.INTERNAL,
                attributes={
                    "faction": ai_state.faction,
                    "game_phase": get_game_phase().value,
                    "cycle_number": decision_count,
                    "cycle_start": datetime.now().isoformat(),
                    "session_start": ai_state.game_start_time.isoformat() if ai_state.game_start_time else None
                }
            ) as cycle_span:
                parent_ctx = baggage.set_baggage("context", "parent")
                try:
                    # Get current game state first to check for threats
                    game_state = get_game_state(parent_ctx)
                    
                    # Check if capital is under threat
                    threats = analyze_threats(game_state)
                    capital_under_threat = any(threat.get('imminent_capital_threat', False) for threat in threats)
                    
                    # Check if we have sufficient defense
                    my_capital = "southern_capital" if ai_state.faction == "southern" else "northern_capital"
                    capital_state = game_state.get(my_capital, {})
                    sufficient_defense = True
                    
                    if capital_under_threat:
                        # Find the imminent threat to check our defense
                        for threat in threats:
                            if threat.get('imminent_capital_threat', False):
                                threat_size = threat['enemy_army_size']
                                current_defense = capital_state.get('army', 0)
                                defense_buffer = 2
                                sufficient_defense = current_defense >= (threat_size + defense_buffer)
                                cycle_span.set_attribute("threat_size", threat_size)
                                cycle_span.set_attribute("current_defense", current_defense)
                                cycle_span.set_attribute("sufficient_defense", sufficient_defense)
                                break
                    
                    # Natural pause between actions - shorter if under threat WITHOUT sufficient defense
                    if capital_under_threat and not sufficient_defense:
                        pause_time = random.randint(2, 5)  # Quick response when under threat
                        logger.warning(f"Capital under threat! AI responding quickly (waiting {pause_time}s)")
                    else:
                        pause_time = random.randint(5, 20)  # Normal pause
                        if capital_under_threat and sufficient_defense:
                            logger.info(f"Capital under threat but has sufficient defense, using normal pause")
                    
                    cycle_span.set_attribute("pause_duration_seconds", pause_time)
                    cycle_span.set_attribute("capital_under_threat", capital_under_threat)
                    logger.info(f"AI waiting {pause_time} seconds before next action")
                    
                    # Use wait instead of sleep to allow interruption
                    if ai_state.stop_flag.wait(pause_time):
                        cycle_span.set_attribute("interrupted", True)
                        break
                    
                    if not ai_state.active:
                        cycle_span.set_attribute("ai_deactivated", True)
                        break
                    
                    # Check if game is over
                    if my_capital not in game_state or game_state[my_capital]['faction'] != ai_state.faction:
                        logger.info("AI detected game over - stopping")
                        cycle_span.set_attribute("game_over_detected", True)
                        cycle_span.set_attribute("final_cycle", True)
                        ai_state.active = False
                        break
                    
                    # Make and execute decision - these will be child spans
                    decision = make_decision(game_state, parent_ctx)
                    if decision:
                        execute_action(decision, parent_ctx)
                        ai_state.last_action_time = datetime.now()
                        cycle_span.set_attribute("action_executed", True)
                        cycle_span.set_attribute("action_type", decision['action'])
                    else:
                        cycle_span.set_attribute("no_action_taken", True)
                    
                    cycle_span.set_attribute("cycle_complete", True)
                    
                    # Add session metrics to each cycle
                    if ai_state.game_start_time:
                        elapsed_time = (datetime.now() - ai_state.game_start_time).total_seconds()
                        cycle_span.set_attribute("session_elapsed_seconds", elapsed_time)
                    
                except Exception as e:
                    cycle_span.record_exception(e)
                    cycle_span.set_status(trace.StatusCode.ERROR, str(e))
                    logger.error(f"Error in AI decision cycle: {str(e)}")
                    time.sleep(5)  # Brief pause on error

@app.route('/activate', methods=['POST'])
def activate_ai():
    """Activate the AI for a specific faction"""
    data = request.get_json()
    faction = data.get('faction')
    
    if faction not in ['southern', 'northern']:
        return jsonify({"success": False, "message": "Invalid faction"}), 400
    
    if ai_state.active:
        return jsonify({"success": False, "message": "AI already active"}), 400
    
    ai_state.faction = faction
    ai_state.active = True
    ai_state.game_start_time = datetime.now()
    ai_state.stop_flag.clear()
    
    # Start AI decision thread
    ai_state.decision_thread = threading.Thread(target=ai_decision_loop, daemon=True)
    ai_state.decision_thread.start()
    
    logger.info(f"AI activated for {faction} faction")
    return jsonify({"success": True, "message": f"AI activated for {faction} faction"})

@app.route('/deactivate', methods=['POST'])
def deactivate_ai():
    """Deactivate the AI"""
    if not ai_state.active:
        return jsonify({"success": False, "message": "AI not active"}), 400
    
    ai_state.active = False
    ai_state.stop_flag.set()
    
    # Wait for thread to stop (with timeout)
    if ai_state.decision_thread:
        ai_state.decision_thread.join(timeout=5)
    
    logger.info("AI deactivated")
    return jsonify({"success": True, "message": "AI deactivated"})

@app.route('/status', methods=['GET'])
def ai_status():
    """Get current AI status"""
    return jsonify({
        "active": ai_state.active,
        "faction": ai_state.faction,
        "last_action": ai_state.last_action_time.isoformat() if ai_state.last_action_time else None,
        "game_phase": get_game_phase().value if ai_state.active else None
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8081))
    app.run(host='0.0.0.0', port=port, debug=False) 