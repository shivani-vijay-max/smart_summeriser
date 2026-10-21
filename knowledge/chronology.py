"""Source-verified employment dates; calendar ordering is done in Python, not by the LLM."""
import calendar
import json
import re
import unicodedata
from collections import defaultdict
from difflib import get_close_matches

MONTHS = {name.lower(): number for number in range(1, 13)
          for name in (calendar.month_name[number], calendar.month_abbr[number])}
MONTHS['sept'] = 9
MONTH_WORD = r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
DATE = r'(?:'+MONTH_WORD+r'\.?\s+(?:19|20)\d{2}|(?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}|(?:19|20)\d{2}[-/](?:0?[1-9]|1[0-2])|(?:19|20)\d{2}|present|current|ongoing|now|today)'
RANGES = re.compile(r'(?<!\w)(?P<start>'+DATE+r')\s*(?:[-–—−]|to|until|through)\s*(?P<end>'+DATE+r')(?!\w)', re.I)

EMPLOYMENT_INSTRUCTIONS = """This is a chronological employment question. Identify the employment
entry with the latest end date in the provided WORK EXPERIENCE / EMPLOYMENT HISTORY sections.
Student and internship roles count as employment. Exclude education degrees and personal projects. Populate
employment_history with the employer name, start_date, end_date, and supporting source_ids.
For a question about employment, a job, role or position, also copy the exact job title into role.
Leave role empty if no title is stated. A professional-summary title is not an employment role.
Copy employer names and date strings EXACTLY from the passages (e.g. 11/2022 and 03/2025);
do not normalize dates or invent Present. Return the relevant employer/date entry; additional jobs are optional.
The application independently compares every date range in the employment section. Passage ranking, resume order, role seniority,
full-time vs student status, and previous assistant answers do NOT determine recency.
If employment dates are missing, do not guess."""


class ChronologyError(ValueError):
    pass


QUESTION_WORDS = {
    'employment', 'employer', 'employers', 'employed', 'company', 'companies',
    'organisation', 'organization', 'job', 'jobs', 'role', 'roles', 'position', 'positions',
    'work', 'worked', 'working', 'recent', 'recently', 'latest', 'last', 'current',
    'currently', 'present', 'now',
}


def one_edit_apart(left, right):
    """One insertion, deletion, substitution, or adjacent transposition."""
    if abs(len(left)-len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = [i for i,(a,b) in enumerate(zip(left,right)) if a != b]
        return len(differences) <= 1 or (len(differences) == 2
            and differences[1] == differences[0]+1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]])
    short, long = (left,right) if len(left) < len(right) else (right,left)
    return any(long[:i]+long[i+1:] == short for i in range(len(long)))


def normalize_employment_question(question):
    """Correct close vocabulary typos for routing/search; preserve the user's stored question."""
    def correct(match):
        word = match[0].casefold()
        if word in QUESTION_WORDS or len(word) < 5:
            return word
        for candidate in get_close_matches(word, sorted(QUESTION_WORDS), n=3, cutoff=0.8):
            if one_edit_apart(word,candidate):
                return candidate
        return word
    return re.sub(r'[a-zA-Z]+',correct,unicodedata.normalize('NFKC',question))


def is_latest_employer_question(question):
    question = normalize_employment_question(question)
    return bool(re.search(r'\b(latest|recent(?:ly)?|last|current(?:ly)?|present|now)\b', question, re.I)
                and re.search(r'\b(employers?|employ(?:ment|ed)|compan(?:y|ies)|organi[sz]ation|jobs?|roles?|positions?|work(?:ed|ing)?)\b', question, re.I))


def normalize(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return re.sub(r'\s+', ' ', re.sub(r'[–—−]', '-', text)).strip()


def date_bounds(raw):
    value = normalize(raw)
    if value in {'present', 'current', 'ongoing', 'now', 'today'}:
        return (9999, 12), (9999, 12)
    if re.fullmatch(r'(19|20)\d{2}', value):
        year = int(value)
        return (year, 1), (year, 12)
    match = re.fullmatch(r'(\d{1,2})[/.-]((?:19|20)\d{2})', value)
    if match:
        month, year = map(int, match.groups())
    else:
        match = re.fullmatch(r'((?:19|20)\d{2})[-/](\d{1,2})', value)
        if match:
            year, month = map(int, match.groups())
        else:
            match = re.fullmatch(r'([a-z]+)\.?\s+((?:19|20)\d{2})', value)
            if not match or match[1] not in MONTHS:
                raise ChronologyError('Unrecognized employment date.')
            month, year = MONTHS[match[1]], int(match[2])
    if not 1 <= month <= 12:
        raise ChronologyError('Invalid employment month.')
    return (year, month), (year, month)


def employment_schema(schema):
    schema = {**schema, 'properties': dict(schema['properties']), 'required': list(schema['required'])}
    schema['properties']['employment_history'] = {
        'type':'array', 'maxItems':30, 'items':{
            'type':'object', 'properties':{
                'employer':{'type':'string'}, 'role':{'type':'string'}, 'start_date':{'type':'string'}, 'end_date':{'type':'string'},
                'source_ids':{'type':'array','items':schema['properties']['source_ids']['items']},
            }, 'required':['employer','role','start_date','end_date','source_ids'], 'additionalProperties':False,
        },
    }
    schema['required'].append('employment_history')
    return schema


def employment_ranges(sources):
    """Use explicit employment section headings to detect omitted date ranges."""
    documents = defaultdict(list)
    for source in sources:
        documents[source['document_id']].append(source)
    found = set()
    for document_id, chunks in documents.items():
        text = '\n'.join(s['excerpt'] for s in sorted(chunks, key=lambda s:s.get('position',s['chunk_id'])))
        headings = list(re.finditer(r'\b(?:WORK EXPERIENCE|PROFESSIONAL EXPERIENCE|EMPLOYMENT HISTORY|EMPLOYMENT EXPERIENCE)\b', text, re.I))
        for heading in headings:
            section = text[heading.end():]
            stop = re.search(r'\b(?:EDUCATION|TECHNICAL SKILLS|SKILLS|PERSONAL PROJECTS|CERTIFICATIONS|INTERESTS)\b', section)
            if stop:
                section = section[:stop.start()]
            for match in RANGES.finditer(section):
                try:
                    found.add((document_id,date_bounds(match['start']),date_bounds(match['end'])))
                except ChronologyError:
                    pass
    return found


def source_supports(source, employer, start, end):
    text = normalize(source['excerpt'])
    name = normalize(employer)
    # Match an employer and its immediately adjacent range, not unrelated dates elsewhere.
    pattern = re.compile(r'(?<![\w/.-])'+re.escape(normalize(start))+r'\s*(?:-|to|until|through)\s*'+re.escape(normalize(end))+r'(?![\w/-]|\.\d)')
    for name_match in re.finditer(re.escape(name), text):
        for dates in pattern.finditer(text):
            if name_match.end() <= dates.start():
                between = text[name_match.end():dates.start()]
            elif dates.end() <= name_match.start():
                between = text[dates.end():name_match.start()]
            else:
                continue
            if len(between) <= 240 and not RANGES.search(between):
                return True
    return False


def supported_role(record, sources):
    # The first entry after an explicit employment heading preserves a full title.
    # This can recover 'Work Student' when the model extracts only 'Student'.
    for source in sources:
        text = unicodedata.normalize('NFKC', source['excerpt'])
        for heading in re.finditer(r'\b(?:WORK EXPERIENCE|PROFESSIONAL EXPERIENCE|EMPLOYMENT HISTORY|EMPLOYMENT EXPERIENCE)\b', text, re.I):
            after = text[heading.end():]
            company = re.search(re.escape(record['employer']),after,re.I)
            if company:
                title = after[:company.start()].strip(' :,-\n')
                if title and len(title) <= 120 and len(title.split()) <= 12 and not RANGES.search(title):
                    return title
    role = record.get('role','')
    if not isinstance(role,str) or not role.strip() or len(role) > 120:
        return ''
    for source in sources:
        text = normalize(source['excerpt'])
        for title in re.finditer(re.escape(normalize(role)),text):
            for company in re.finditer(re.escape(normalize(record['employer'])),text):
                if title.end() <= company.start():
                    between = text[title.end():company.start()]
                elif company.end() <= title.start():
                    between = text[company.end():title.start()]
                else:
                    continue
                if len(between) <= 60 and not RANGES.search(between) and not re.search(r'\b(work experience|employment history|professional experience)\b',between):
                    return role.strip()
    return ''


def resolve_latest_employer(raw, sources, question):
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise ChronologyError('Return valid JSON with all employment entries.') from None
    if not isinstance(payload,dict) or not isinstance(payload.get('employment_history'),list):
        raise ChronologyError('Extract all employment entries and their original date ranges.')
    evidence = {s['id']:s for s in sources}
    expected = employment_ranges(sources)
    covered, records = set(), {}
    for item in payload['employment_history']:
        if not isinstance(item,dict) or any(not isinstance(item.get(k),str) or not item[k].strip() for k in ['employer','start_date','end_date']):
            continue
        ids = item.get('source_ids')
        if not isinstance(ids,list) or not ids or any(not isinstance(i,str) or i not in evidence for i in ids):
            continue
        try:
            start, end = date_bounds(item['start_date']), date_bounds(item['end_date'])
        except ChronologyError:
            continue
        if start[0] > end[1] or start[0][0] == 9999:
            continue
        # Independently resolve citations by literal evidence, rather than trusting
        # the small model's source-number guess. Only already-retrieved sources qualify.
        supported = [i for i,source in evidence.items() if source_supports(source,item['employer'],item['start_date'],item['end_date'])]
        if not supported:
            continue
        for i in supported:
            covered.add((evidence[i]['document_id'],start,end))
        key = (normalize(item['employer']),start,end)
        records[key] = {**item,'source_ids':supported,'start':start,'end':end}
    if not records:
        if expected:
            raise ChronologyError('Employment dates are present. Extract the employer attached to the latest end date.')
        return json.dumps({'answerable':False,'answer':'Employment dates are not specified.','source_ids':[]})
    ordered = sorted(records.values(), key=lambda r:(r['end'][1],r['start'][1]), reverse=True)
    winner = ordered[0]
    # Date ranges come directly from the employment section, independently of model output.
    # Omitting older jobs is harmless; omitting a possibly newer job is not.
    for _, start, end in expected - covered:
        if (end[1],start[1]) > (winner['end'][1],winner['start'][1]):
            raise ChronologyError(f'A newer employment date range ends in {end[1][0]}-{end[1][1]:02d}. Extract the employer next to that original date range instead.')
        if end != winner['end'] and end[1] >= winner['end'][0]:
            raise ChronologyError('The employment date ranges overlap in precision; the latest employer is ambiguous.')
    for other in ordered[1:]:
        if winner['end'] != other['end'] and winner['end'][0] <= other['end'][1]:
            raise ChronologyError('The available dates are too imprecise to distinguish the latest employer.')
        if winner['end'] == other['end'] and winner['start'][0] <= other['start'][1] and normalize(winner['employer']) != normalize(other['employer']):
            raise ChronologyError('Multiple employers have indistinguishable latest employment dates.')
    interpreted = normalize_employment_question(question)
    current = bool(re.search(r'\b(current(?:ly)?|present|now)\b',interpreted,re.I))
    job_question = bool(re.search(r'\b(employment|jobs?|roles?|positions?|work)\b',interpreted,re.I))
    kind = 'employment' if job_question else 'employer'
    role = supported_role(winner,[evidence[i] for i in winner['source_ids']]) if job_question else ''
    detail = f"{role} at {winner['employer']}" if role else winner['employer']
    prefix = f'No ongoing {kind} is explicitly stated. The most recent {kind} listed was' if current and winner['end'][0][0] != 9999 else f'The most recent {kind} listed is'
    answer = f"{prefix} {detail} ({winner['start_date']} – {winner['end_date']})."

    return json.dumps({'answerable':True,'answer':answer,'source_ids':winner['source_ids']})
