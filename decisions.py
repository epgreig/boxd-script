"""Independent generation from source + editable decisions, never an import CSV."""
import json
from datetime import date
from pathlib import Path

def read_policy(home):
    private = Path(home)/'private'
    return json.loads((private/'rules.json').read_text()), json.loads((private/'decisions.json').read_text())

def rating_for(entry, rules, decision):
    if 'rating' in decision:
        return decision['rating']['final'], decision['rating']['reason']
    tier = entry['tier']
    if tier in rules['tier_ratings']:
        return rules['tier_ratings'][tier], 'Tier mapping: '+tier
    old = entry['old']
    key = f'{old:g}'
    if key not in rules['numerical_ratings']:
        raise ValueError('No rating rule for '+key)
    return rules['numerical_ratings'][key], 'Numerical rule: old '+key

def year_for(key, rules, decision):
    if 'watched' in decision:
        return decision['watched']['year'], decision['watched']['reason']
    order = rules['historical_order']
    if key not in order:
        raise ValueError('No historical watch-year decision for '+key)
    index = order.index(key)
    year = None
    for boundary in rules['watch_partitions']:
        if index >= order.index(boundary['first_key']):
            year = boundary['year']
    if year is None:
        raise ValueError('Missing watch year or explicit unknown for '+key)
    return year, 'Approved chronological partition'

def make_row(entry, rules, policy, format_review):
    key = entry['key']
    if key not in rules['historical_order']:
        raise ValueError('New films require explicit metadata: '+key)
    d = policy['films'].get(key, {})
    rating, _ = rating_for(entry, rules, d)
    if not isinstance(rating, (int,float)) or not .5 <= rating <= 5 or rating*2 != int(rating*2):
        raise ValueError('Invalid final rating for '+key)
    year, _ = year_for(key, rules, d)
    watched = '' if year is None else date(int(year),1,1).isoformat()
    metadata = d.get('identity', {})
    liked = d.get('liked', entry['tier'] in rules['liked_tiers'])
    return dict(Title=metadata.get('title',entry['title']), Year=str(metadata.get('year',entry['year'])),
                Rating=f'{rating:g}', Review=format_review(entry), Liked=str(bool(liked)).lower(), WatchedDate=watched)

def register(entries, rules, policy, format_review):
    lines = ['# Decision register', '',
             'Edit private/decisions.json for individual overrides and private/rules.json for general rules. Then rerun decisions.',
             'This register is derived, not an input. Null watch years mean intentionally unknown.', '',
             '| Film | Old | Final | Rating basis | Watch year | Date basis | Review |',
             '|---|---:|---:|---|---|---|---|']
    for e in entries:
        if e['key'] not in rules['historical_order']:
            continue
        d = policy['films'].get(e['key'], {})
        r = make_row(e,rules,policy,format_review)
        _, rb = rating_for(e,rules,d)
        year, yb = year_for(e['key'],rules,d)
        values=[r['Title']+' ('+r['Year']+')',str(e['old']),r['Rating'],rb,str(year) if year is not None else 'Unknown',yb,'Redacted' if not r['Review'] else 'Included']
        lines.append('| '+' | '.join(v.replace('|','\\|').replace('\n',' ') for v in values)+' |')
    return '\n'.join(lines)+'\n'
