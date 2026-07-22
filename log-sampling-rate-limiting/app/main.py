import random
import datetime
import time
import json
# Data for the script

DEBUG = [
    "cache lookup for key=X",
    "entering function Y"
]

INFO = [
    "request handled",
    "user logged in"
]

WARN = [
    "retrying connection",
    "deprecated field used"
]

ERROR = [
    "failed to connect to DB",
    "unhanded exception in handler"
]

levels = {"DEBUG": DEBUG, "INFO": INFO, "WARN": WARN, "ERROR": ERROR}

#Clean the file
with open("/logs/app.log", "a") as f:
    pass

# loop the lists
while True:
    # Random pick from the list
    # Pick a random element from the
    # DEBUG,INFO,WARN and ERROR lists.
    choice = random.choices(list(levels.keys()), weights = [60,20,10,10], k=1)[0]
    message_choice = random.choice(levels[choice])

    # Build a Python dict with the following
    # keys: level, message, timestamp.
    json_object = {"level": choice, "message": message_choice, "timestamp": datetime.datetime.now().isoformat()}
    # Convert the dict into JSON string
    json_string = json.dumps(json_object)
    # Write to file path
    with open("/logs/app.log", "a") as f:
        f.write(json_string + "\n")
    time.sleep(0.1)