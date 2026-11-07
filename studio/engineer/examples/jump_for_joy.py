# Example plug-in action. Copy this shape: four constants and run(api, ev).
ACTION = "jump_for_joy"                      # new lowercase_name, never a built-in action
DESCRIPTION = "who jumps twice for joy with both arms up (about 1.4 s)"   # what the producer reads
NEEDS = ["who"]                              # event fields that must be present: who (a puppet), name (a spawned prop), at, to, text
PARAMS = "jump_for_joy {who}"                # one-line usage for the producer


def run(api, ev):
    p = api.puppet(ev["who"])               # the Puppet: root, body, mouth, pupils, arms, size, kind
    t = float(ev["t"])                       # start time in seconds
    api.hop(p, t, height=0.5)                # reuse built-in moves where you can
    api.hop(p, t + 0.7, height=0.5)
    for side, pivot in p.arms:               # side is -1 (left) or +1 (right)
        up = (0, -side * 2.3, 0)             # this rotation raises that arm (the same one wave uses)
        api.key(pivot, "rotation_euler", api.F(t), (0, 0, 0))
        api.key(pivot, "rotation_euler", api.F(t + 0.2), up)
        api.key(pivot, "rotation_euler", api.F(t + 1.2), up)
        api.key(pivot, "rotation_euler", api.F(t + 1.4), (0, 0, 0))
