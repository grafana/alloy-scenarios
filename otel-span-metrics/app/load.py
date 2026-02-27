import requests, time, random
endpoints = ["http://app:5000/", "http://app:5000/api/data", "http://app:5000/api/slow"]
while True:
    try:
        url = random.choice(endpoints[:2])  # mostly hit fast endpoints
        if random.random() < 0.1:
            url = endpoints[2]  # occasionally hit slow
        requests.get(url, timeout=5)
    except:
        pass
    time.sleep(random.uniform(0.5, 2.0))
