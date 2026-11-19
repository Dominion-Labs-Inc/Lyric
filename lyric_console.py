#!/usr/bin/env python3
"""Lyric Console — the running system, read from outside it.

Run: venv_lyric/bin/python3 lyric_console.py
Use a UTF-8 terminal, preferably 140+ columns by 42+ rows.

A SEPARATE PROCESS ON PURPOSE. Attaching or closing a viewer must never affect
the run it is watching, so this holds no state the system depends on: close it
and nothing changes. It starts nothing and controls nothing.

WATCHING IS READ-ONLY. CHAT IS THE ONE THING HERE THAT SPEAKS, and it speaks
through the running model's own door (`core/integration/instance_door.py`) --
the same front door the web platform and LyricOS reach it through, named for
the environment it is called from, so a console turn is one caller among them
and not a second way in. The conversation is the person's own.

NOTHING HERE KNOWS WHERE THE DATA LIVES. The status read belongs to
`lyric-systems` and the channel names to `core/observability/channels.py`, and
both are loaded here by path, in isolation, exactly the way `lyric-dash` does it:
importing the `core` package would pull in the whole cognitive stack to answer a
question about health. Each reader stays the one owner of what it reads; this
file only draws.

Telemetry is read on a worker thread, so a slow database can never hold up a
keystroke. The screen always shows the last good reading and says how old it is.
"""
from __future__ import annotations

import asyncio
import curses
import getpass
import importlib.machinery
import importlib.util
import json
import math
import os
import re
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, relative: str):
    """Load one module by path, WITHOUT executing `core/__init__.py`.

    `import core.observability.channels` runs the whole package chain first, and
    `core/__init__.py` pulls in the tool registry -- measured at ~9.8s, which a
    viewer that refreshes every two seconds cannot pay. Both files loaded here
    import only the standard library, so loading them directly is safe.
    """
    if name in sys.modules:
        return sys.modules[name]
    path = HERE / relative
    spec = importlib.util.spec_from_loader(
        name, importlib.machinery.SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    # REGISTER BEFORE EXECUTING: a frozen dataclass in the module resolves its
    # fields through sys.modules, and omitting this leaves that None.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[name]
        raise
    return module


# LOADED WHEN THEY ARE NEEDED, NOT WHEN THIS FILE IS. Reading this host needs
# both; reading the console service needs neither, and on a laptop neither file
# is there at all. Importing them at the top would have made the remote console
# refuse to start on every machine that is not this one.
def _systems():
    return _load("lyric_console_systems", "lyric-systems")


def _channels():
    return _load("lyric_console_channels", "core/observability/channels.py")


@dataclass(frozen=True)
class Row:
    name: str
    status: str
    attention: bool = False
    down: bool = False
    detail: tuple = ()


@dataclass
class Reading:
    """One complete look at the system. Replaced whole, never patched."""
    models: tuple = ()
    systems: tuple = ()
    activity: tuple = ()
    runtime: tuple = ()
    at: float = 0.0
    error: str = ''


@dataclass(frozen=True)
class Turn:
    """One thing said in the console's conversation with the model."""
    who: str
    said: str
    at: str
    trouble: bool = False


# How a component is named on screen. The health monitor's own identifiers are
# module names; these are the same subsystems said the way the console says
# everything else. Anything absent from this map is title-cased from its id, so
# a component added to the manifest appears without an edit here.
DISPLAY = {
    'memory': 'Memory', 'learning': 'Learning', 'reasoning': 'Reasoning',
    'domain': 'Domain', 'agents': 'Agents', 'intelligence': 'Intelligence',
    'tools': 'Tools', 'constitution': 'Constitution', 'safety': 'Safety',
    'security': 'Security', 'firewall': 'Firewall', 'api_surface': 'API surface',
    'simulation': 'Simulation', 'optimization': 'Optimization', 'chaos': 'Chaos',
    'database': 'Database', 'storage': 'Storage',
    'network': 'Network', 'backup': 'Backup', 'utils': 'Utilities',
    'health_system': 'Health', 'system_awareness': 'Awareness',
    'metrics_export': 'Metrics',
}

# The health system's words, said the console's way. ONLINE and ATTENTION are
# the two the console was drawn around; the rest are real states it must be able
# to show rather than round off to one of those two.
STATE = {
    'healthy': 'ONLINE', 'degraded': 'ATTENTION', 'unhealthy': 'DOWN',
    'critical': 'DOWN', 'offline': 'OFFLINE', 'unknown': 'UNKNOWN',
    'running': 'ONLINE', 'stopped': 'STOPPED', 'absent': 'NOT BUILT',
    'gate': 'GATE',
}

# Which faculty a log line is speaking for, by the logger that wrote it.
FACULTY = {
    'semantics': 'Language', 'memory': 'Memory', 'learning': 'Learning',
    'reasoning': 'Reasoning', 'domain': 'Domain', 'agents': 'Agents',
    'intelligence': 'Intelligence', 'health': 'Health', 'security': 'Security',
    'database': 'Database', 'tools': 'Tools', 'monitoring': 'Metrics',
    'integration': 'Integration', 'services': 'Services', 'system': 'Awareness',
    'api': 'API surface', 'utils': 'Utilities', 'chaos': 'Chaos',
}

_LINE = re.compile(r'^\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d) +(\w+) +([\w.]+) \| (.*)$')

# The substrate decorates some of its lines with emoji. They are double-width,
# and curses counts cells rather than characters, so one of them shifts every
# column to its right by one. Dropped on the way in, not worked around later.
_WIDE = re.compile(r'[^\u0000-\u2fff]')

# The faculties lead, in the order the console was drawn with, and everything
# else follows alphabetically. A component absent from here is not special-cased;
# it simply sorts after the named ones.
PREFERRED = ('memory', 'reasoning', 'learning', 'domain', 'agents',
             'intelligence', 'tools', 'constitution', 'safety', 'security')

# Who owns a system, in words. The health system's key for the model's own
# process is "substrate": that is what the code calls the process, not what the
# thing is called. The thing is the Lyric world model, and the console says so.
OWNER_SAID = {
    'substrate': 'Owned by the world model.',
    'system': 'Owned by the guardian, which stays up on its own.',
}

# Quantum reasoning does not run: it has no IBM access and qiskit_algorithms is
# not installed, so the health monitor declares it with monitoring off and it
# publishes nothing. A console that listed it would be naming a faculty the
# system does not have.
EXCLUDED = frozenset({'quantum'})


def _pretty(name: str) -> str:
    return DISPLAY.get(name, name.replace('_', ' ').capitalize())


def _build() -> str:
    """The commit the tree is on. Read once; the console never shells out again."""
    try:
        out = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(HERE),
                             capture_output=True, text=True, timeout=2)
        return out.stdout.strip() or 'unknown build'
    except Exception:
        return 'unknown build'


BUILD = _build()


def _tail(path: Path, limit: int = 64 * 1024) -> list:
    """The end of a log file. These reach hundreds of megabytes, so seek."""
    try:
        size = path.stat().st_size
        with path.open('rb') as handle:
            if size > limit:
                handle.seek(size - limit)
                handle.readline()
            return handle.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return []


class Telemetry:
    """Everything the console shows, read from the running system every 2s.

    The read happens on a worker thread and lands as one whole `Reading`, so the
    key loop never waits on the database and the screen never shows half of one
    reading beside half of another.
    """

    PERIOD = 2.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reading = Reading()
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> Reading:
        with self._lock:
            return self._reading

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                reading = self._read()
            except Exception as error:
                reading = Reading(at=time.time(),
                                  error='%s: %s' % (type(error).__name__, error))
                previous = self.snapshot()
                if previous.systems:
                    reading.models = previous.models
                    reading.systems = previous.systems
                    reading.activity = previous.activity
                    reading.runtime = previous.runtime
                    reading.at = previous.at
            with self._lock:
                self._reading = reading
            self._stop.wait(self.PERIOD)

    # -- the read ---------------------------------------------------------

    def _read(self) -> Reading:
        status = asyncio.run(_systems()._status())['systems']
        parts = asyncio.run(_systems()._components())
        components = parts['components']

        by_name = {row['name']: row for row in status}
        heartbeat = by_name.get('__substrate_heartbeat__')
        age = heartbeat['age_seconds'] if heartbeat else None
        said = heartbeat['status'] if heartbeat else None

        instance = asyncio.run(_systems()._instance()).get('instance')
        models = self._models(said, age, instance)
        systems = self._systems(components, status)
        activity = self._activity()
        runtime = self._runtime(models, components)
        return Reading(models=models, systems=systems, activity=activity,
                       runtime=runtime, at=time.time())

    #: A heartbeat older than this says nothing about now.
    #:
    #: MEASURED, not assumed. The control loop intends one every two seconds,
    #: and over 376 reads in 45s it managed 14 -- normally 0 to 4 seconds old,
    #: but spiking to 23 while the model was busy. At eight seconds the console
    #: would have called a working model STOPPED every time it was under load,
    #: which is exactly when somebody is watching. Thirty still notices a model
    #: that has gone within half a minute.
    STALE_AFTER = 30

    def _models(self, said, age, instance=None) -> tuple:
        """The Lyric world model, and any model made after it.

        TWO THINGS DECIDE WHAT IT SAYS, and neither works alone. The age says
        whether anybody is still writing; the word says what they are doing.
        A row left behind by a process that died still reads 'running', and a
        model coming up is every bit as fresh as one that is up.

        One world model runs today, so one is listed. A model this cannot see
        is not one it will invent.
        """
        fresh = age is not None and age <= self.STALE_AFTER
        beat = 'Heartbeat %ss ago.' % (age if age is not None else '?')
        named = ['Instance %s.' % instance['name']] if instance else []

        if fresh and said == 'starting':
            return (Row('World model', 'STARTING · %ss' % age,
                        attention=True,
                        detail=tuple(['The Lyric world model is coming up.']
                                     + named
                                     + [beat,
                                        'Its systems answer as they start.'])),)
        if fresh and said == 'running':
            return (Row('World model', 'LIVE · %s' % BUILD,
                        detail=tuple(['The Lyric world model is running.']
                                     + named
                                     + [beat, 'Build %s.' % BUILD])),)

        seen = 'last seen %ss ago' % age if age is not None else 'never seen'
        return (Row('World model', 'STOPPED · %s' % seen, down=True,
                    detail=('The Lyric world model is not running.',
                            'Its cognition is graded with it, so those',
                            'systems read offline rather than failed.')),)

    def _systems(self, components: list, status: list) -> tuple:
        """Every system the health monitor grades, cognition first.

        Grouped the way ownership is declared: the world model's own
        faculties, then the machinery the guardian keeps up whether the world
        model is running or not. The controlled systems that publish no component health are listed
        after them, so nothing the console knows about is left off the page.
        """
        def rank(component):
            name = component['name']
            at = PREFERRED.index(name) if name in PREFERRED else len(PREFERRED)
            return (at, name)

        rows, seen = [], set()
        for owner in ('substrate', 'system'):
            for component in sorted(components, key=rank):
                if component['owner'] != owner or component['name'] in EXCLUDED:
                    continue
                name = component['name']
                seen.add(name)
                word = STATE.get(component['status'], component['status'].upper())
                score = component['health_score']
                rows.append(Row(
                    _pretty(name),
                    '%s · %.1f%%' % (word, score * 100),
                    attention=component['status'] == 'degraded',
                    down=component['status'] in ('unhealthy', 'critical'),
                    detail=('%s · %s' % (component['category'], component['type']),
                            'Health %.3f, %s.' % (score, word.lower()),
                            'Checked %ss ago.' % component['checked_age'],
                            OWNER_SAID[owner])))
        for system in status:
            name = system['name']
            if name.startswith('__') or name in seen or name in EXCLUDED:
                continue
            word = STATE.get(system['status'], system['status'].upper())
            rows.append(Row(
                _pretty(name), word,
                attention=system['status'] == 'stopped',
                detail=(system['description'],
                        'Reported %ss ago.' % system['age_seconds'],
                        'Can be started and stopped.' if system['controllable']
                        else 'No lifecycle to report.')))
        return tuple(rows)

    def _activity(self) -> tuple:
        """The world model's own lines, newest last, from the channel files.

        Every record already carries `core.<subsystem>`, so which faculty spoke
        is read off the logger rather than guessed at from the message.
        """
        out = []
        channels = _channels()
        directory = channels.log_dir()
        if not directory.is_absolute():
            directory = HERE / directory
        for channel in channels.ALL_CHANNELS:
            for line in _tail(directory / ('%s.log' % channel))[-400:]:
                found = _LINE.match(line)
                if not found:
                    continue
                stamp, level, logger, message = found.groups()
                if level == 'DEBUG':
                    continue
                parts = logger.split('.')
                faculty = FACULTY.get(parts[1] if len(parts) > 1 else '', 'System')
                said = _WIDE.sub('', message).strip()
                if said:
                    out.append((stamp, '%s — %s' % (faculty, said)))
        out.sort(key=lambda row: row[0])
        return tuple(out[-14:])

    def _runtime(self, models: tuple, components: list) -> tuple:
        """The three figures, each counted from what was just read.

        A model coming up is counted as coming up, not as nought online. "0
        models online" beside sixteen healthy systems told a reader two things
        that could not both be true and left them to pick.
        """
        online = sum(1 for model in models if model.status.startswith('LIVE'))
        starting = sum(1 for model in models if model.status.startswith('STARTING'))
        healthy = sum(1 for c in components if c['status'] == 'healthy')
        if starting and not online:
            first = '%d model%s starting' % (starting, '' if starting == 1 else 's')
        else:
            first = '%d model%s online' % (online, '' if online == 1 else 's')
        return (first,
                '%d/%d healthy systems' % (healthy, len(components)),
                ('{:,} concepts held'.format(CONCEPTS[0]) if CONCEPTS[0] >= 0
                 else 'counting concepts'))


#: Filled once by the first read; a count over a million rows is not worth
#: repeating every two seconds.
CONCEPTS = [-1]


def _count_concepts() -> None:
    async def go():
        conn = await _systems()._connect()
        try:
            return await conn.fetchval('SELECT count(*) FROM unified.concepts')
        finally:
            await conn.close()
    try:
        CONCEPTS[0] = int(asyncio.run(go()))
    except Exception:
        CONCEPTS[0] = -1


#: Who the console is signed in as, when it is reading the service. Empty when
#: it is reading this host directly.
SIGNED_IN: list = ['']

#: True when reading this host's database directly, with nobody signed in. The
#: page says so rather than looking the same as a session that was authorized.
LOCAL: list = [False]


def _request(url: str, headers: dict, body=None, timeout: float = 20.0) -> dict:
    """One HTTP request, and ONE place that turns a refusal into words.

    The readings and the chat both come through here, and both the console
    service and a running Lyric's own door answer a refusal as a sentence --
    `detail` from the service, `refused` from the door. Said as it was given,
    because the thing refusing knows why and this does not.
    """
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method='POST' if data is not None else 'GET',
        headers=dict(headers, **({'Content-Type': 'application/json'} if data else {})))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return json.loads(answer.read().decode() or '{}')
    except urllib.error.HTTPError as error:
        said = {}
        try:
            said = json.loads(error.read().decode() or '{}')
        except Exception:
            pass
        detail = said.get('detail') or said.get('refused')
        if error.code in (401, 403):
            raise RuntimeError(detail or 'Your session has ended. Run: lyric login')
        raise RuntimeError(detail or 'Answered %d.' % error.code)


class RemoteTelemetry(Telemetry):
    """The same console, reading the Lyric Console service instead of the host.

    THE SCREEN DOES NOT CHANGE. Only where the numbers come from changes, which
    is the whole point of this class existing rather than a second console: one
    drawing, two sources, so the thing an operator sees on the host and the
    thing a developer sees on a laptop cannot drift apart.

    WHAT IS DRAWN IS WHAT THE SERVICE SENT. A role that may not see a reading
    does not receive it, so a missing score is drawn as missing rather than
    filled in from somewhere else. This class never decides what may be shown;
    it would be the wrong place to, because it runs on the viewer's machine.
    """

    def __init__(self, api: str, token: str, device: str = '') -> None:
        super().__init__()
        self.api = api.rstrip('/')
        self.token = token
        #: Which machine is asking. The service ties a session to the first
        #: device that uses it, so this travels on every request or the
        #: console is refused -- which is the point of it.
        self.device = device or os.getenv('LYRIC_CONSOLE_DEVICE', '')

    def headers(self) -> dict:
        return {'Authorization': 'Bearer ' + self.token,
                'User-Agent': 'lyric-console',
                'X-Lyric-Device': self.device}

    def _get(self, path: str) -> dict:
        return _request(self.api + path, self.headers())

    def _read(self) -> Reading:
        models_answer = self._get('/api/console/models')
        models, systems, activity, runtime = [], (), (), ()

        for model in models_answer.get('models', []):
            state = model.get('state', '')
            age = model.get('heartbeat_age_seconds')
            said = state + ('' if age is None else ' · heartbeat %ss' % age)
            models.append(Row(
                model.get('name', model.get('id', '?')), said,
                down=state != 'LIVE',
                detail=tuple(filter(None, (
                    'Instance %s.' % model['instance'] if model.get('instance') else None,
                    'Read through the console service.',
                    'Signed in as %s.' % (SIGNED_IN[0] or 'someone'))))))

        if models:
            first = models_answer['models'][0]['id']
            systems = self._systems_of(first)
            activity = self._activity_of(first)
            runtime = self._runtime_of(first)

        return Reading(models=tuple(models), systems=systems,
                       activity=activity, runtime=runtime, at=time.time())

    def _systems_of(self, model: str) -> tuple:
        answer = self._get('/api/console/models/%s/systems' % model)
        rows = []
        for row in answer.get('systems', []):
            state = row.get('state', '')
            health = row.get('health')
            said = state if health is None else '%s · %.1f%%' % (state, health * 100)
            detail = [row.get('description') or '%s · %s' % (
                row.get('category') or '—', row.get('type') or '—')]
            if health is not None:
                detail.append('Health %.3f, %s.' % (health, state.lower()))
            if row.get('checked_age_seconds') is not None:
                detail.append('Checked %ss ago.' % row['checked_age_seconds'])
            detail.append('Owned by the %s.' % row.get('owner', '—'))
            rows.append(Row(row.get('name', '?'), said,
                            attention=state == 'ATTENTION',
                            down=state in ('DOWN', 'STOPPED'),
                            detail=tuple(detail)))
        return tuple(rows)

    def _activity_of(self, model: str) -> tuple:
        try:
            answer = self._get('/api/console/models/%s/activity?limit=40' % model)
        except RuntimeError:
            # A role that may not read the channels is not an error on the
            # page: the panel is simply empty, and the role already says why.
            return ()
        return tuple((line['at'], '%s — %s' % (line['faculty'], line['said']))
                     for line in answer.get('activity', []))

    def _runtime_of(self, model: str) -> tuple:
        answer = self._get('/api/console/models/%s/runtime' % model)
        out = []
        for figure in answer.get('figures', []):
            value = figure.get('value')
            shown = '{:,}'.format(value) if isinstance(value, int) else str(value)
            if figure.get('of') is not None:
                shown = '%s/%s' % (shown, figure['of'])
            out.append('%s %s' % (shown, figure.get('label', '')))
        return tuple(out)


class Chat:
    """The console's conversation with the model: what was said, and the turn in flight.

    THE TURN IS TAKEN ON A WORKER THREAD. Measured against the running model, a
    turn comes back in ten to twenty seconds, and the key loop redraws every
    110ms: waiting for it on the drawing thread would stop the globe, the
    readings and the keyboard for the whole of it, and a console that freezes
    for twenty seconds reads as a console that has died.

    ONE TURN AT A TIME FROM THIS SCREEN. That is this screen's manner -- a
    person types one thing and reads the answer before typing the next -- and
    not a limit of the model, which takes turns from everyone speaking to it at
    once. Nothing here holds a lock on anything but its own transcript.

    THE TRANSCRIPT LIVES IN THIS PROCESS. Close the console and it is gone.
    What the model remembers of the conversation is the model's, under the
    conversation's own name, and it is still there at the next sign-in.
    """

    #: How long to wait for a turn. NOT A LIMIT ON THINKING: the door answers
    #: when the turn has been taken. This is so that a socket to a process that
    #: has died is not held open for ever.
    WAIT = 300.0

    def __init__(self, who: str = '') -> None:
        self.who = who
        self._lock = threading.Lock()
        self._turns: list = []
        self._since = 0.0

    @property
    def conversation(self) -> str:
        """What the model calls this conversation: `<environment>:<identity>`."""
        return 'console:%s' % (self.who or 'this host')

    def snapshot(self) -> tuple:
        """Every turn, and when the one in flight was sent. Read whole."""
        with self._lock:
            return tuple(self._turns), self._since

    def waiting(self) -> bool:
        with self._lock:
            return bool(self._since)

    def speak(self, said: str) -> bool:
        """Say something. Returns at once; the answer lands in the transcript.

        SAYS WHETHER IT TOOK THE WORDS, rather than leaving the caller to ask
        afterwards: a turn can be answered before the next line of the caller
        runs, and `waiting()` would then read False for a turn that was sent --
        which cleared the composer or did not by luck of timing.
        """
        said = said.strip()
        if not said:
            return False
        with self._lock:
            if self._since:
                return False
            self._turns.append(Turn('You', said, time.strftime('%H:%M')))
            self._since = time.monotonic()
        threading.Thread(target=self._take, args=(said,), daemon=True).start()
        return True

    def _take(self, said: str) -> None:
        try:
            answer, trouble = self._ask(said), False
        except Exception as error:
            # WHATEVER REFUSED SAYS WHY, in its own words. A console that
            # replaced them with one of its own would send someone looking for
            # the trouble in the wrong place.
            answer, trouble = str(error) or type(error).__name__, True
        with self._lock:
            self._turns.append(Turn('Lyric', answer, time.strftime('%H:%M'), trouble))
            self._since = 0.0

    def _ask(self, said: str) -> str:
        raise NotImplementedError


class LocalChat(Chat):
    """Speaking to the model on this host, through its own door.

    A running Lyric writes its address and a key to
    `runtime/instances/<instance>.json`, mode 0600, and the reader of that is
    `instance_door.running_instances` -- loaded here by path like every other
    reader, so the lookup keeps one owner.

    A RECORD OUTLIVES THE PROCESS THAT WROTE IT, so `runtime/instances/` says
    "running" long after nothing is: of the eight records on this host, seven
    were left by processes that are gone. So the records are candidates, newest
    first, and the turn itself finds the one that is listening.
    """

    def __init__(self) -> None:
        # Nobody is signed in here, so the conversation is named for whoever is
        # at the machine. Said plainly rather than borrowing a person's name.
        super().__init__('%s@%s' % (getpass.getuser(),
                                    socket.gethostname().split('.')[0]))

    def _candidates(self) -> list:
        """Every instance that could be the world model, newest first.

        `lyric_dev` is the store the tests own, and a turn reaches the world
        model or it reaches nothing: answering out of a test store would be
        answering as the wrong Lyric and saying nothing about it.
        """
        doors = _load('lyric_console_instance_door', 'core/integration/instance_door.py')
        found = []
        for name, record in doors.running_instances().items():
            if not record.get('door') or not record.get('key'):
                continue
            database = str(record.get('database') or '')
            if not database or database.endswith('_dev'):
                continue
            found.append((str(record.get('started_at') or ''), name, record))
        found.sort(reverse=True)
        return [record for _, _, record in found]

    def _ask(self, said: str) -> str:
        """Take the turn at the first door that answers.

        THE TURN IS THE TEST. This asked each door `/health` first and only
        spoke to one that said it was ready -- and a model halfway through the
        previous turn cannot answer anything in three seconds, so a running
        world model was reported absent while it was working. The same mistake
        the heartbeat made at eight seconds. Trying is a better test than
        asking, and it is the test that has to pass anyway.

        A TURN IS NEVER SENT TWICE. The next door is tried only where this one
        cannot have taken it: the port was not open, or the door itself said no
        -- a wrong key, or a worker, which takes queued work and never a turn.
        A turn that was sent and then went slow or went wrong is reported, not
        repeated.
        """
        refusals = []
        for record in self._candidates():
            try:
                answered = _request(record['door'] + '/turn',
                                    {'Authorization': 'Bearer ' + record['key']},
                                    {'identity': self.who, 'text': said,
                                     'environment': 'console'}, self.WAIT)
            except urllib.error.URLError as error:
                # Nothing was sent: this port is not open. Seven of the eight
                # records on this host were left behind by processes that are
                # gone, so this is the ordinary case, not a fault.
                refusals.append(str(getattr(error, 'reason', error)))
                continue
            refused = answered.get('refused')
            if refused:
                refusals.append(refused)
                continue
            return answered.get('answer') or 'The model answered with nothing.'
        raise RuntimeError(refusals[0] if len(refusals) == 1
                           else 'No world model on this host is taking turns.')


class RemoteChat(Chat):
    """Speaking to the model through the console service.

    WHO IS SPEAKING IS NOT SENT. The service takes the identity from the token
    it already checked, so this sends only the words -- a console on somebody's
    laptop cannot name itself as somebody else. It is also the service, not
    this, that decides whether this person's role may speak to the model at
    all; a refusal comes back as the reason and lands in the transcript.
    """

    #: The one model that answers today. The service knows it by the same name.
    MODEL = 'world'

    def __init__(self, telemetry: RemoteTelemetry, who: str = '') -> None:
        super().__init__(who)
        self._telemetry = telemetry

    def _ask(self, said: str) -> str:
        answered = _request(
            '%s/api/console/models/%s/chat' % (self._telemetry.api, self.MODEL),
            self._telemetry.headers(), {'said': said}, self.WAIT)
        answer = answered.get('answer') or ''
        if not answered.get('success'):
            raise RuntimeError(answer or 'The turn was not taken.')
        return answer


#: The turning marker shown while a turn is in flight. Braille, like the globe,
#: so the console has one alphabet for movement.
SPINNER = '\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f'


def orbital_sphere(cols: int, rows: int, phase: float) -> list:
    """Project rotating spherical meridians, parallels and tilted orbits onto Braille dots."""
    pixels = [[0] * cols for _ in range(rows)]
    bits = ((1, 8), (2, 16), (4, 32), (64, 128))
    cx, cy = cols, rows * 2
    radius = min(cols * .68, rows * 1.82)

    def plot(x: float, y: float, z: float) -> None:
        yaw = phase
        x, z = x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)
        tilt = .18
        y, z = y * math.cos(tilt) - z * math.sin(tilt), y * math.sin(tilt) + z * math.cos(tilt)
        px, py = round(cx + x * radius * 1.18), round(cy - y * radius)
        if 0 <= px < cols * 2 and 0 <= py < rows * 4:
            pixels[py // 4][px // 2] |= bits[py % 4][px % 2]

    for j in range(12):
        lon = j * math.tau / 12
        for i in range(100):
            lat = i * math.tau / 100
            plot(math.cos(lat) * math.cos(lon), math.sin(lat), math.cos(lat) * math.sin(lon))
    for j in range(-3, 4):
        lat = j * math.pi / 9
        for i in range(120):
            lon = i * math.tau / 120
            plot(math.cos(lat) * math.cos(lon), math.sin(lat), math.cos(lat) * math.sin(lon))
    for angle in (.25, -.46, 1.15):
        for i in range(160):
            t = i * math.tau / 160
            plot(1.48 * math.cos(t), 1.48 * math.sin(t) * math.sin(angle), 1.48 * math.sin(t) * math.cos(angle))
    return [''.join(chr(0x2800 + p) if p else ' ' for p in row) for row in pixels]


def main(screen: curses.window) -> None:
    curses.curs_set(0)
    screen.keypad(True)
    screen.timeout(110)
    curses.start_color()
    curses.use_default_colors()
    for index, color in enumerate((curses.COLOR_WHITE, curses.COLOR_GREEN,
                                   curses.COLOR_YELLOW, curses.COLOR_RED), 1):
        curses.init_pair(index, color, -1)
    WHITE, GREEN, AMBER, RED = (curses.color_pair(i) for i in (1, 2, 3, 4))
    DIM, BOLD = WHITE | curses.A_DIM, WHITE | curses.A_BOLD

    # TWO SOURCES, ONE SCREEN. With an address and a token in the environment
    # this reads the console service, which is how it runs on a laptop: the
    # service decides what the person's role may see. With neither, it reads
    # this host directly, which is how an operator runs it here -- and that
    # still works when the gateway does not.
    api = os.getenv('LYRIC_CONSOLE_API')
    token = os.getenv('LYRIC_CONSOLE_TOKEN')
    if api and token:
        telemetry = RemoteTelemetry(api, token)
        SIGNED_IN[0] = os.getenv('LYRIC_CONSOLE_WHO', '')
        chat = RemoteChat(telemetry, SIGNED_IN[0])
    else:
        # READING THIS HOST DIRECTLY, WITH NO SIGN-IN. That is deliberate --
        # an operator at the machine must be able to see the model when the
        # gateway is down -- but it means a shell on this host is the whole
        # of the authorization. Reached over SSH it handed the console to
        # anyone with the account, which is not what anyone intended, so it
        # has to be asked for in as many words rather than fallen into.
        LOCAL[0] = True
        telemetry = Telemetry()
        chat = LocalChat()
        threading.Thread(target=_count_concepts, daemon=True).start()
    telemetry.start()

    selected = 0
    scroll = 0
    overlay = ''
    query = ''
    start = time.monotonic()

    # TWO VIEWS, ONE SCREEN: the overview is what the console watches, the chat
    # is what it says. The header has always named the view it is showing --
    # "World model / Overview" -- so the chat is named there the same way
    # rather than opening a window over the top of the page.
    view = 'chat' if os.getenv('LYRIC_CONSOLE_VIEW') == 'chat' else 'overview'
    composing = ''
    # Lines held back from the bottom of the transcript. Nought is pinned to
    # the newest, which is where a conversation is read from, so an answer that
    # lands while nobody has scrolled is simply there.
    chat_scroll = 0
    # UTF-8 ARRIVES ONE BYTE AT A TIME. curses hands over bytes, so one typed
    # or pasted character outside ASCII is two to four calls; they are held
    # here until they make a character.
    pending = bytearray()

    def put(y: int, x: int, s: str, attr: int = WHITE) -> None:
        h, w = screen.getmaxyx()
        if 0 <= y < h and 0 <= x < w - 1:
            try:
                screen.addnstr(y, x, s, w - x - 1, attr)
            except curses.error:
                pass

    def rule(y: int, x: int, width: int) -> None:
        put(y, x, '─' * max(0, width), DIM)

    def tone(row: Row) -> int:
        return RED if row.down else AMBER if row.attention else GREEN

    def transcript(turns, width: int) -> list:
        """The conversation as display lines, so scrolling and drawing agree.

        One list, built once: a transcript measured one way and drawn another
        is a transcript that scrolls past the line it is pointing at.
        """
        out = []
        for turn in turns:
            if out:
                out.append(('gap', turn, ''))
            out.append(('who', turn, ''))
            # The model answers in sentences and sometimes in paragraphs. Its
            # own breaks are kept; only the long lines are folded.
            for paragraph in turn.said.splitlines() or ['']:
                for line in textwrap.wrap(paragraph, max(16, width)) or ['']:
                    out.append(('said', turn, line))
        return out

    def put_transcript(x: int, top: int, room: int, lines: list,
                       scroll: int, stamps: bool = True) -> None:
        """What was said, oldest first down the page, newest at the bottom.

        ANCHORED TO THE BOTTOM OF ITS ROOM, not the top. A conversation is read
        where it is being added to, and the turn just answered belongs beside
        the line the next one is typed into. Grown downward from the top
        instead, the first two turns sat twenty-five rows above the composer
        with the whole page empty between them.
        """
        indent = 7 if stamps else 0
        first = max(0, len(lines) - room - scroll)
        shown = lines[first:first + room]
        base = top + max(0, room - len(shown))
        for offset in range(len(shown)):
            kind, turn, text = shown[offset]
            y = base + offset
            if kind == 'gap':
                continue
            if kind == 'who':
                if stamps:
                    put(y, x, turn.at, DIM)
                # The model's name in weight, the person's plain: a
                # conversation has to be scannable without colour, because a
                # terminal somewhere will not have any.
                put(y, x + indent, turn.who,
                    BOLD if turn.who == 'Lyric' else WHITE)
            else:
                put(y, x + indent, text, RED if turn.trouble else WHITE)

    def put_composer(left: int, right: int, rule_y: int, since: float,
                     label: bool = True) -> None:
        """The line being typed, and whether the model is still taking a turn."""
        rule(rule_y, left, right - left)
        if label:
            put(rule_y + 1, left, 'Y O U', BOLD)
        if since:
            waited = int(time.monotonic() - since)
            turning = SPINNER[int(time.monotonic() * 8) % len(SPINNER)]
            said = '%s Taking the turn · %ds' % (turning, waited)
            put(rule_y + 1, max(left, right - len(said)), said, AMBER)
        elif label:
            put(rule_y + 1, max(left, right - 13), 'Enter to send', DIM)
        width = max(4, right - left - 4)
        shown = composing[-width:]
        put(rule_y + 2, left, '› ', DIM)
        put(rule_y + 2, left + 2, shown + '▊', WHITE)

    def put_footer(w: int, h: int, reading, shortcuts) -> None:
        """The key bar and who is patched in. One for both views."""
        left, right = 2, w - 3
        footer = h - 4
        rule(footer, left, right - left)
        x = left
        for key, label in shortcuts:
            if x + len(key) + len(label) + 7 >= right - 24:
                break
            put(footer + 1, x, ' %s ' % key, WHITE | curses.A_REVERSE)
            x += len(key) + 3
            put(footer + 1, x, label)
            x += len(label) + 3
        if reading.error:
            session = 'Disconnected'
        elif SIGNED_IN[0]:
            session = 'Connected · %s' % SIGNED_IN[0]
        elif LOCAL[0]:
            # Not a session at all. Said plainly, so nobody reads an
            # unauthorized console as an authorized one.
            session = 'Reading this host directly · no sign-in'
        else:
            session = 'Connected · Internal session'
        put(footer + 1, right - len(session) - 2, '●',
            GREEN if not reading.error else RED)
        put(footer + 1, right - len(session), session, DIM)

    def draw_chat(w: int, h: int, reading) -> None:
        """The conversation, given the page.

        THE GLOBE DOES NOT COME HERE. It is the console's mark, and it costs a
        third of the height; on this view the height is the conversation, which
        is the thing somebody came to read. The page keeps its header, its key
        bar and the line saying who is patched in, so it is plainly the same
        console with a different view open.
        """
        left, right = 2, w - 3
        footer = h - 4
        turns, since = chat.snapshot()

        put(1, left, '$ lyric console ▊')
        put(3, left, 'World model', BOLD)
        put(3, left + 12, '/ Chat', DIM)
        named = chat.conversation
        put(3, max(left + 22, right - len(named)), named, DIM)
        rule(4, left, right - left)

        put(6, left, 'C O N V E R S A T I O N', BOLD)
        # A TURN IS ONE PERSON'S TURN, ANSWER AND ALL -- which is what the
        # model's own `take_turn` means by it. Counting both sides called one
        # exchange "2 turns".
        taken = sum(1 for turn in turns if turn.who == 'You')
        count = '%d turn%s' % (taken, '' if taken == 1 else 's')
        put(6, right - len(count), count, DIM)

        compose_rule = footer - 3
        top = 8
        room = max(1, compose_rule - 1 - top)
        lines = transcript(turns, right - left - 7)

        if not turns:
            put(top, left, 'Speak to the Lyric world model: type below, '
                           'then press Enter.', DIM)
            put(top + 1, left, 'Your words reach its front door and its answer '
                               'comes back here.', DIM)
            put(top + 3, left, 'This conversation is yours. The model keeps it '
                               'under %s;' % named, DIM)
            put(top + 4, left, 'the transcript on this screen closes with the '
                               'console.', DIM)
        else:
            put_transcript(left, top, room, lines, chat_scroll)

        held = max(0, len(lines) - room - chat_scroll)
        if held:
            put(7, right - 12, '▲ %d earlier' % held, DIM)
        if chat_scroll:
            put(compose_rule, right - 12, ' ▼ %d later ' % chat_scroll, DIM)

        put_composer(left, right, compose_rule, since)
        put_footer(w, h, reading, [('Enter', 'Send'), ('↑ ↓', 'Scroll'),
                                   ('Esc', 'Overview')])

    def draw_chat_narrow(w: int, h: int, reading) -> None:
        """The conversation on a phone: one column, no timestamp gutter.

        The stamps go first because seven columns of "14:32" out of forty is a
        sixth of every line the model says, and somebody reading a conversation
        on their phone knows roughly when they sent it.
        """
        left, right = 1, w - 1
        turns, since = chat.snapshot()

        put(0, left, 'LYRIC', BOLD)
        put(0, max(left, right - 4), 'CHAT', DIM)
        put(1, left, chat.conversation[:right - left], DIM)
        rule(2, left, right - left)

        compose_rule = h - 4
        top = 3
        room = max(1, compose_rule - top)
        lines = transcript(turns, right - left)

        if not turns:
            put(top, left, 'Type below, then Enter.', DIM)
            put(top + 1, left, 'Esc returns to the overview.', DIM)
        else:
            put_transcript(left, top, room, lines, chat_scroll, stamps=False)

        put_composer(left, right, compose_rule, since, label=False)

        # ON THE RULES, AND AFTER THEM. A scrolling list that does not say
        # there is more above it looks like the whole of it, which is the one
        # thing a scrolling list must never do -- and on a phone the room is
        # six or seven lines, so there usually is more.
        held = max(0, len(lines) - room - chat_scroll)
        if held:
            put(2, max(left, right - 7), ' ▲ %d ' % held, DIM)
        if chat_scroll:
            put(compose_rule, max(left, right - 7), ' ▼ %d ' % chat_scroll, DIM)

        hint = '⏎ send  ↑↓ scroll  Esc overview'
        put(h - 1, left, hint[:right - left], DIM)

    def draw_narrow(w: int, h: int, reading, rows) -> None:
        """The console on a phone: one column, same readings, nothing invented.

        What goes and why: the globe and the wordmark are the mark, not the
        instrument, and they cost a third of the screen. The activity panel
        needs width to say anything -- a log line cut at forty columns is
        noise -- so it appears only when there is room for it. What stays is
        what someone patching in from a phone actually came for: which models
        are up, which systems are not well, and the figures.
        """
        nonlocal scroll
        left = 1
        right = w - 1
        models_n = len(reading.models)

        state = reading.models[0].status.split(' · ')[0] if reading.models else '—'
        put(0, left, 'LYRIC', BOLD)
        put(0, max(left, right - len(state)), state,
            tone(reading.models[0]) if reading.models else DIM)
        age = '' if not reading.at else '%ds ago' % int(time.time() - reading.at)
        if reading.error:
            age = 'no answer'
        put(1, left, 'World model / Overview'[:w - 2 - len(age)], DIM)
        put(1, max(left, right - len(age)), age, DIM)
        rule(2, left, right - left)

        # Every row, models and systems together: on one column the two are
        # one list, and the selection already runs across both.
        top = 3
        foot = h - 2
        # The runtime figures sit above the key bar when there is room.
        if h >= 16:
            foot -= 2
        room = max(1, foot - top)

        if not rows:
            put(top, left, 'Reading the world model…' if not reading.error
                else 'Cannot read the world model.', DIM)
        else:
            if selected < scroll:
                scroll = selected
            elif selected >= scroll + room:
                scroll = selected - room + 1
            scroll = max(0, min(scroll, max(0, len(rows) - room)))

            # The state column is pinned off the right edge so the names have
            # the width, which is the scarce thing here.
            state_at = max(len(' • ') + 6, w - 22)
            for offset in range(min(room, len(rows) - scroll)):
                index = scroll + offset
                row = rows[index]
                y = top + offset
                active = selected == index
                attr = WHITE | curses.A_REVERSE if active else WHITE
                if active:
                    put(y, left, ' ' * (right - left), attr)
                lead = '▼ ' if index == 0 and models_n else ' • '
                put(y, left, (lead + row.name)[:state_at - left - 1], attr)
                put(y, state_at, '●', tone(row))
                put(y, state_at + 2, row.status[:max(0, right - state_at - 2)], attr)

        if h >= 16:
            rule(h - 4, left, right - left)
            figures = ' · '.join(reading.runtime)
            put(h - 3, left, figures[:right - left], WHITE)

        # AFTER the rules, and on them. Drawn before, they were painted over,
        # so a list with eight more systems under it looked like the whole of
        # it -- the one thing a scrolling list must never do.
        if rows:
            if scroll:
                put(2, max(left, right - 8), ' ▲ %d ' % scroll, DIM)
            below = max(0, len(rows) - scroll - room)
            if below:
                put(min(foot, h - 4), max(left, right - 8), ' ▼ %d ' % below, DIM)

        hint = '↑↓ move  ⏎ inspect  C chat  / search  Q exit'
        put(h - 1, left, hint[:right - left], DIM)

    def draw() -> None:
        nonlocal scroll
        reading = telemetry.snapshot()
        rows = reading.models + reading.systems

        screen.erase()
        h, w = screen.getmaxyx()
        if w < 36 or h < 10:
            put(0, 1, 'LYRIC', BOLD)
            put(2, 1, 'Screen too small.', DIM)
            put(3, 1, 'Q exits.', DIM)
            screen.refresh()
            return
        # A PHONE IS A NARROW TERMINAL, NOT A BROKEN ONE. The wide screen is
        # two columns beside a turning globe and needs 120 x 34; an iPhone in
        # landscape gives about 90 x 25, and refusing to draw anything at all
        # meant someone who had patched in from their phone saw a sentence
        # telling them to get a bigger phone. The same readings, one column.
        narrow = w < 120 or h < 34
        if view == 'chat':
            (draw_chat_narrow if narrow else draw_chat)(w, h, reading)
            screen.refresh()
            return
        if narrow:
            draw_narrow(w, h, reading, rows)
            screen.refresh()
            return

        left, right = 2, w - 3
        split = int(w * .462)
        top_rule = int(h * .39)
        footer = h - 4
        put(1, left, '$ lyric console ▊')

        # Hero matches the reference: orbital graphic, vertical hairline, wordmark.
        art_h = max(7, top_rule - 5)
        art_w = min(44, int(w * .30))
        hero_x = int(w * .09)
        for i, line in enumerate(orbital_sphere(art_w, art_h, (time.monotonic() - start) * .10)):
            put(3 + i, hero_x, line, WHITE)
        divider = int(w * .375)
        mid = 3 + art_h // 2
        for y in range(mid - 3, mid + 4):
            put(y, divider, '│', DIM)
        brand_x = divider + 5
        put(mid - 2, brand_x, 'L   Y   R   I   C', BOLD)
        put(mid + 1, brand_x, 'C O G N I T I V E   C O N S O L E')
        put(mid + 3, brand_x, 'D O M I N I O N   L A B S', DIM)
        rule(top_rule, left, right - left)

        put(top_rule + 1, left, 'World model', BOLD)
        put(top_rule + 1, left + 12, '/ Overview', DIM)
        age = '' if not reading.at else 'read %ds ago' % int(time.time() - reading.at)
        if reading.error:
            age = reading.error[:46]
        put(top_rule + 1, right - len(age), age, DIM)

        section = top_rule + 3
        for y in range(section, footer):
            put(y, split, '│', DIM)
        put(section, left, 'M O D E L  E X P L O R E R', BOLD)
        put(section, split + 3, 'L I V E  A C T I V I T Y', BOLD)
        status_x = int(split * .52)
        name_w = max(8, status_x - left - 4)
        status_w = max(8, split - status_x - 5)

        if not rows:
            put(section + 2, left, 'Reading the world model…' if not reading.error
                else 'Cannot read the world model.', DIM)

        # Models always show; the systems list scrolls under them, so a long
        # manifest never pushes the explorer off its own page.
        models_n = len(reading.models)
        for i, row in enumerate(reading.models):
            y = section + 2 + i
            active = selected == i
            attr = WHITE | curses.A_REVERSE if active else WHITE
            if active:
                put(y, left, ' ' * (split - left - 2), attr)
            put(y, left, ('▼ ' if i == 0 else '   ├─ ') + row.name[:name_w], attr)
            put(y, status_x, '●', tone(row))
            put(y, status_x + 3, row.status[:status_w], attr)

        sys_label_y = section + 2 + models_n + 1
        sys_top = sys_label_y + 2
        avail = max(1, footer - 1 - sys_top)
        put(sys_label_y, left, 'S Y S T E M S', BOLD)

        systems = reading.systems
        if selected >= models_n:
            index = selected - models_n
            if index < scroll:
                scroll = index
            elif index >= scroll + avail:
                scroll = index - avail + 1
        scroll = max(0, min(scroll, max(0, len(systems) - avail)))

        for offset in range(min(avail, len(systems) - scroll)):
            index = scroll + offset
            row = systems[index]
            y = sys_top + offset
            active = selected == models_n + index
            attr = WHITE | curses.A_REVERSE if active else WHITE
            if active:
                put(y, left, ' ' * (split - left - 2), attr)
            put(y, left, '•  ' + row.name[:name_w], attr)
            put(y, status_x, '●', tone(row))
            put(y, status_x + 3, row.status[:status_w], attr)

        hidden_above, hidden_below = scroll, max(0, len(systems) - scroll - avail)
        if hidden_above:
            put(sys_top - 1, status_x, '▲ %d more' % hidden_above, DIM)
        if hidden_below:
            put(footer - 1, status_x, '▼ %d more' % hidden_below, DIM)

        # Live activity fills the room it has, then the runtime figures.
        rx = split + 3
        rt_label_y = footer - 3
        rt_y = footer - 1
        rt_rule_y = footer - 5
        room = max(1, (rt_rule_y - 1 - (section + 2)) // 2)
        shown = reading.activity[-room:]
        for i, (stamp, message) in enumerate(shown):
            y = section + 2 + i * 2
            put(y, rx, '[%s]' % stamp, DIM)
            put(y, rx + 13, message[:max(0, right - rx - 14)])
        rule(rt_rule_y, rx, right - rx)
        put(rt_label_y, rx, 'R U N T I M E', BOLD)
        x = rx
        for i, metric in enumerate(reading.runtime):
            if x + len(metric) + 4 >= right:
                break
            put(rt_y, x, '●', GREEN)
            put(rt_y, x + 2, metric)
            x += len(metric) + 4
            if i < len(reading.runtime) - 1 and x < right:
                put(rt_y, x, '│', DIM)
                x += 2

        put_footer(w, h, reading,
                   [('↑ ↓', 'Navigate'), ('Enter', 'Inspect'), ('C', 'Chat'),
                    ('/', 'Search'), ('?', 'Help'), ('Q', 'Exit')])

        if overlay:
            box_w = min(76, w - 8)
            # Eleven rows: rule, title, gap, status, four lines of detail, gap,
            # the close hint, rule. At ten the hint landed on the fourth detail
            # line and the two printed over each other.
            box_h = 11
            # Clear of the page's own rules: an overlay that opened on the
            # section rule merged with it and read as collided text.
            bx = (w - box_w) // 2
            by = max(section + 1, (h - box_h) // 2)
            for line in range(box_h):
                put(by + line, bx, ' ' * box_w, WHITE)
            rule(by, bx, box_w)
            rule(by + box_h - 1, bx, box_w)
            if overlay == 'inspect' and rows:
                row = rows[min(selected, len(rows) - 1)]
                put(by + 1, bx + 2, row.name + ' / Inspect', BOLD)
                put(by + 3, bx + 2, row.status)
                for i, line in enumerate(row.detail[:4]):
                    put(by + 4 + i, bx + 2, line[:box_w - 4], DIM)
            elif overlay == 'search':
                put(by + 1, bx + 2, 'SEARCH MODELS & SYSTEMS', BOLD)
                put(by + 3, bx + 2, '/ ' + query + '▊')
                hits = [r.name for r in rows if query.lower() in r.name.lower()]
                put(by + 5, bx + 2, '%d of %d match' % (len(hits), len(rows)), DIM)
                put(by + 6, bx + 2, ', '.join(hits[:6])[:box_w - 4], DIM)
            else:
                put(by + 1, bx + 2, 'LYRIC CONSOLE / HELP', BOLD)
                put(by + 3, bx + 2, '↑ ↓ select · Enter inspect · C chat · / search · Q exit')
                put(by + 4, bx + 2, 'Watching is read-only: this process starts and', DIM)
                put(by + 5, bx + 2, 'controls nothing. Chat takes a turn with the model', DIM)
                put(by + 6, bx + 2, 'through its own front door, in your conversation.', DIM)
                put(by + 7, bx + 2, 'Build %s · refreshed every %.0fs'
                    % (BUILD, Telemetry.PERIOD), DIM)
            put(by + box_h - 2, bx + 2, 'Esc Close', DIM)
        screen.refresh()

    try:
        while True:
            draw()
            count = len(telemetry.snapshot().models) + len(telemetry.snapshot().systems)
            key = screen.getch()

            # THE CHAT VIEW OWNS THE KEYBOARD WHILE IT IS OPEN. Every printable
            # key is a character there, Q included -- a view you type into
            # cannot keep a letter as the way out -- so Esc is the way back and
            # the key bar says so.
            if view == 'chat':
                if key == -1:
                    continue
                if key == 27:
                    # ESC IS ALSO THE FIRST BYTE OF EVERY ARROW KEY, and this
                    # terminfo names the arrows in SS3 (`ESC O A`), so a
                    # terminal that sends the other form (`ESC [ A`) hands over
                    # three bytes curses does not recognise -- and a bare 27
                    # taken as "go back" threw someone out of the chat for
                    # pressing Up. So the rest of the sequence is looked for
                    # before the 27 is believed, and read rather than typed.
                    screen.timeout(25)
                    trailing = []
                    while True:
                        more = screen.getch()
                        if more == -1:
                            break
                        trailing.append(more)
                    screen.timeout(110)
                    if not trailing:
                        # What was typed is kept: looking something up on the
                        # overview and coming back should not cost the sentence.
                        view, pending = 'overview', bytearray()
                    elif trailing[0] in (ord('['), ord('O')):
                        last = trailing[-1]
                        if last == ord('A'):
                            chat_scroll += 1
                        elif last == ord('B'):
                            chat_scroll = max(0, chat_scroll - 1)
                        elif last == ord('5'):
                            chat_scroll += 8
                        elif last == ord('6'):
                            chat_scroll = max(0, chat_scroll - 8)
                        # Anything else the terminal sends in a sequence is
                        # left alone rather than written into the line.
                elif key in (10, 13, curses.KEY_ENTER):
                    # The line is cleared only if it was taken. Nothing said,
                    # or a turn still in flight, leaves it there to send.
                    if chat.speak(composing):
                        composing, chat_scroll = '', 0
                elif key in (127, 8, curses.KEY_BACKSPACE):
                    composing, pending = composing[:-1], bytearray()
                elif key == 21:                       # Ctrl-U, as in a shell
                    composing, pending = '', bytearray()
                elif key == curses.KEY_UP:
                    chat_scroll += 1
                elif key == curses.KEY_DOWN:
                    chat_scroll = max(0, chat_scroll - 1)
                elif key == curses.KEY_PPAGE:
                    chat_scroll += 8
                elif key == curses.KEY_NPAGE:
                    chat_scroll = max(0, chat_scroll - 8)
                elif 32 <= key <= 126:
                    if len(composing) < 4000:
                        composing += chr(key)
                elif 128 <= key <= 255:
                    # A character outside ASCII arrives as its bytes, so a
                    # pasted curly quote is three of these. Held until they
                    # make a character, and dropped rather than written as
                    # mojibake if they never do.
                    pending.append(key)
                    try:
                        composing += pending.decode()
                        pending = bytearray()
                    except UnicodeDecodeError:
                        if len(pending) >= 4:
                            pending = bytearray()
                continue

            if overlay == 'search':
                if key in (27, 10, 13, curses.KEY_ENTER):
                    overlay = ''
                elif key in (127, 8, curses.KEY_BACKSPACE):
                    query = query[:-1]
                elif 32 <= key <= 126 and len(query) < 50:
                    query += chr(key)
                if query and count:
                    rows = telemetry.snapshot().models + telemetry.snapshot().systems
                    selected = next((i for i, row in enumerate(rows)
                                     if query.lower() in row.name.lower()), selected)
                continue
            if key == 27 and overlay:
                overlay = ''
            elif key in (ord('q'), ord('Q')):
                break
            elif not overlay and key == curses.KEY_UP and count:
                selected = (selected - 1) % count
            elif not overlay and key == curses.KEY_DOWN and count:
                selected = (selected + 1) % count
            elif not overlay and key == curses.KEY_HOME and count:
                selected = 0
            elif not overlay and key == curses.KEY_END and count:
                selected = count - 1
            elif key in (10, 13, curses.KEY_ENTER):
                overlay = 'inspect'
            elif key == ord('/'):
                overlay, query = 'search', ''
            elif key == ord('?'):
                overlay = 'help'
            elif not overlay and key in (ord('c'), ord('C')):
                view, chat_scroll = 'chat', 0
    finally:
        telemetry.stop()


def _refuse_unasked_local() -> None:
    """Before the screen is taken over, not after.

    Reading this host's database directly asks for no sign-in: that is right
    for an operator sitting at the machine and wrong for anything else, and
    over SSH it was being fallen into rather than chosen. So it has to be
    said out loud. Checked here because `curses.wrapper` owns the terminal
    from its first line, and a message raised inside it never reaches anyone.
    """
    if os.getenv('LYRIC_CONSOLE_API') and os.getenv('LYRIC_CONSOLE_TOKEN'):
        return
    if os.getenv('LYRIC_CONSOLE_LOCAL') == '1':
        return
    raise SystemExit(
        '\nThis reads the database on this host directly and asks for no sign-in,\n'
        'so it is meant for an operator at the machine.\n\n'
        '  lyric                                       sign in, then the console\n'
        '  LYRIC_CONSOLE_LOCAL=1 python3 lyric_console.py   this host, no sign-in\n')


if __name__ == '__main__':
    _refuse_unasked_local()
    curses.wrapper(main)
