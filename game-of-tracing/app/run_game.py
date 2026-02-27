import os
import sys
import json
import sqlite3
import argparse
import multiprocessing
from game_config import LOCATIONS, DATABASE_FILE
from location_server import LocationServer

def reset_game():
    """Reset the database to initial state"""
    db_path = os.environ.get('DATABASE_FILE', DATABASE_FILE)
    
    if os.path.exists(db_path):
        # Connect to database and reset it
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Delete all data
        cursor.execute("DELETE FROM locations")
        
        # Reinitialize locations
        for loc_id, loc_info in LOCATIONS.items():
            cursor.execute(
                "INSERT INTO locations VALUES (?, ?, ?, ?)",
                (
                    loc_id,
                    loc_info["initial_resources"],
                    loc_info["initial_army"],
                    loc_info["faction"]
                )
            )
        
        conn.commit()
        conn.close()
        print(f"Game reset successfully. Database {db_path} reset to initial state.")
    else:
        print("Database not found. It will be created when the game starts.")

def run_location(location_id):
    """Run a location server in a separate process"""
    print(f"Starting {LOCATIONS[location_id]['name']} (Port: {LOCATIONS[location_id]['port']})")
    server = LocationServer(location_id)
    server.run()

def run_single_location():
    """Run a single location server based on environment variable"""
    location_id = os.environ.get('LOCATION_ID')
    if not location_id:
        print("Error: LOCATION_ID environment variable not set")
        sys.exit(1)
        
    if location_id not in LOCATIONS:
        print(f"Error: Invalid location_id '{location_id}'")
        sys.exit(1)
        
    print(f"Starting {LOCATIONS[location_id]['name']} server (Port: {LOCATIONS[location_id]['port']})")
    server = LocationServer(location_id)
    server.run()

def show_game_state():
    """Show the current game state from the database"""
    db_path = os.environ.get('DATABASE_FILE', DATABASE_FILE)
    
    if not os.path.exists(db_path):
        print("Database not found. Starting a new game...")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM locations")
        rows = cursor.fetchall()
        
        if not rows:
            print("No game state found. Starting a new game...")
            return
        
        print("Current Game State:")
        for row in rows:
            loc_id = row['id']
            print(f"{LOCATIONS[loc_id]['name']} ({loc_id}): Faction={row['faction']}, Army={row['army']}, Resources={row['resources']}")
        
        conn.close()
    except sqlite3.Error as e:
        print(f"Error accessing database: {e}")
        print("Starting a new game...")

def run_game(reset=False):
    """Run all location servers"""
    if reset:
        reset_game()
    
    # Check if we're in Docker and should run just one location
    if os.environ.get('LOCATION_ID'):
        run_single_location()
        return

    # Show initial game state
    show_game_state()
    
    # Start each location server in a separate process
    processes = []
    for location_id in LOCATIONS:
        p = multiprocessing.Process(target=run_location, args=(location_id,))
        p.start()
        processes.append(p)
    
    print("\nAll locations are running!")
    print("Game Instructions:")
    print("1. Each location is running a Flask server at its designated port")
    print("2. Use HTTP requests to interact with locations")
    print("3. Example commands:")
    print("   - Get location info: curl http://localhost:[PORT]/")
    print("   - Collect resources: curl -X POST http://localhost:[PORT]/collect_resources")
    print("   - Create army: curl -X POST http://localhost:[PORT]/create_army")
    print("   - Move army: curl -X POST -H \"Content-Type: application/json\" -d '{\"target_location\":\"village_1\"}' http://localhost:[PORT]/move_army")
    print("   - Reset game: curl -X POST http://localhost:[PORT]/reset")
    print("4. Or use the game client: python game_client.py map")
    
    try:
        # Wait for processes to complete (they won't unless terminated)
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\nShutting down all servers...")
        for p in processes:
            p.terminate()
        print("Game ended.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="War of Westeros Game")
    parser.add_argument("--reset", action="store_true", help="Reset the game state")
    args = parser.parse_args()
    
    run_game(args.reset) 