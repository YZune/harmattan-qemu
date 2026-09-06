"""Stable, nonempty Home observations before the unchanged startup gates."""
import time


def settle(observe, compare, validate, drain, timeout=20, quiet_seconds=5):
    started = time.monotonic()
    previous, matches, samples, stable_since = None, 0, 0, started
    while time.monotonic() - started < timeout:
        current = observe()
        samples += 1
        try:
            validate(current)
        except ValueError:
            previous, matches = None, 0
        else:
            matches = matches + 1 if previous is not None and compare(previous, current) else 0
            if not matches:
                stable_since = time.monotonic()
            previous = current
            if matches >= 2 and time.monotonic() - stable_since >= quiet_seconds:
                return {'samples': samples, 'seconds': round(time.monotonic() - started, 3),
                        'quiet_seconds': quiet_seconds,
                        'scope': 'stable nonempty Home including original scrollbar fade; not display FPS'}
        drain(.25)
    raise TimeoutError('original Home did not stay nonempty and unchanged for the required quiet period')
