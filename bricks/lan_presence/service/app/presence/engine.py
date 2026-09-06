def evaluate(devices, people, now, healthy):
    def device_state(device):
        if not healthy or device['last_seen'] is None:
            return 'UNKNOWN'
        age = max(0, now - device['last_seen'])
        timeout = device['away_timeout_seconds']
        if age >= timeout:
            return 'AWAY'
        return 'HOME' if age < min(300, timeout / 2) else 'UNKNOWN'

    def aggregate(states):
        if 'HOME' in states:
            return 'HOME'
        return 'AWAY' if states and all(state == 'AWAY' for state in states) else 'UNKNOWN'

    device_states = {d['id']: device_state(d) for d in devices}
    persons = []
    for person in people:
        tracked = [d for d in devices if d['presence_enabled'] and d['person_id'] == person['id']]
        persons.append({**person, 'state': aggregate([device_states[d['id']] for d in tracked]), 'tracked_devices': len(tracked)})
    state = aggregate([p['state'] for p in persons])
    reason = {'HOME': 'A tracked person has a recently confirmed device.',
              'AWAY': 'All configured people have tracked devices past their away timeout.',
              'UNKNOWN': 'Discovery is unavailable, evidence is aging, or tracking is incomplete.'}[state]
    return {'state': state, 'reason': reason, 'people': persons, 'devices': device_states}
