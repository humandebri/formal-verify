import argparse
from app import Counter
p=argparse.ArgumentParser(); p.add_argument('--fixed',action='store_true'); a=p.parse_args()
c=Counter(a.fixed)
for event in ('start', 'reset', 'complete'):
    observed = c.event(event)
    print(event, observed)
    assert observed <= 1, f'counter exceeded capacity after {event}: {observed}'
