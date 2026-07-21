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

# Random pick from the list
# Pick a random element from the
# DEBUG,INFO,WARN and ERROR lists.

# Build a Python dict with the following
# keys: level, message, timestamp.

# Convert the dict into JSON string

# loop the lists

# Write to file path