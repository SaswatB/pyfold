# Comments and original spelling live in the reconstruction sidecar.
def active_names(users):
    return [user.name.strip() for user in users if user.active]


def greet(name: str, excited: bool = False) -> str:
    suffix = '!' if excited else '.'  # Keep this exact quote style on round trip.
    return f'Hello, {name}{suffix}'


def once(fetch, consume):
    value = fetch()
    return consume(value, value)


# Complex Python remains explicit and editable.
class Counter:
    def __init__(self):
        self.value = 0

    def increment(self):
        self.value += 1
