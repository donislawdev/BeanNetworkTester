"""A fake tkinter good enough to build the whole GUI headlessly.

CI containers have no Tk, and the container the assistant works in has none
either. The previous fake was a single ``__getattr__`` no-op widget, so no test
could ever see a layout problem (``winfo_width`` was hard-coded to 400 and
``pack``/``grid`` did nothing). This one records geometry calls and models the
handful of widgets whose behaviour the app actually depends on - which is what
makes ``test_gui_layout`` / ``test_gui_state`` possible.

Install it BEFORE importing ``beantester.gui``; do that in a subprocess so the
fakes never leak into the rest of the pytest session.
"""
import sys
import types

SCREEN = [1920, 1080]     # mutable: tests can pretend to be on a 1366x768 laptop
DPI = [96.0]
CLIPBOARD = []            # what the app copied (Ctrl+C, "copy row", repro CLI)
GRAB = [None]             # what currently holds the Tk grab (an open popdown)
CLASS_BINDINGS = {}       # (widget class, sequence) -> handler, set by bind_class
FOCUS = [None]            # the widget holding keyboard focus (ttk paints it)


class TclError(Exception):
    pass


class Var:
    def __init__(self, master=None, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class W:
    """A widget that remembers its parent, its options and its geometry calls."""

    def __init__(self, *args, **kw):
        self.kw = dict(kw)
        self.children = []
        self.commands = []          # menu entries
        self.pack_info = None
        self.grid_info = None
        self.bindings = {}
        self.states = set()         # ttk widget state flags (active, focus, ...)
        self.alive = True
        self._yview = (0.0, 1.0)    # everything fits until a test says otherwise
        self.scrolled = []          # every scroll the widget was asked to do
        master = args[0] if args else kw.get("master")
        self.master = master if isinstance(master, W) else None
        if isinstance(master, W):
            master.children.append(self)

    def _path(self):
        return f".!{type(self).__name__.lower()}"

    def _alive_or_raise(self, reason="invalid command name"):
        """Real Tk deletes the widget's command: touching it afterwards raises.

        Only the two calls that the real teardown crashes made - ``configure`` and
        ``geometry`` - are modelled. The rest stay permissive on purpose: this is a
        test double, not a second implementation of Tk, and every method that
        starts raising is a way for an unrelated test to fail for a fake reason.
        """
        if not self.alive:
            raise TclError(f'{reason} "{self._path()}"')

    # -- options ------------------------------------------------------------ #
    def configure(self, *a, **kw):
        self._alive_or_raise()
        self.kw.update(kw)

    config = configure

    def cget(self, key):
        return self.kw.get(key, "")

    def __setitem__(self, key, value):
        self.kw[key] = value

    def __getitem__(self, key):
        return self.kw.get(key)

    # -- geometry ----------------------------------------------------------- #
    def pack(self, **kw):
        # `before=` / `after=` name a SIBLING. Real Tk refuses a widget that lives
        # in another container ("window ... isn't packed") - and since GUI code
        # wraps its pack calls, that refusal is silent: the widget then exists, has
        # its text, even reports winfo_ismapped(), and draws nothing. That bug
        # shipped once (the queue-overflow banner) and only a screenshot found it.
        # The fake now refuses too, so a test can find it instead.
        for anchor in ("before", "after"):
            sibling = kw.get(anchor)
            if sibling is not None and getattr(sibling, "master", None) is not self.master:
                raise RuntimeError(
                    f"cannot pack {anchor}={sibling!r}: it is not a sibling "
                    f"(its parent is {getattr(sibling, 'master', None)!r}, "
                    f"ours is {self.master!r})")
        self.pack_info = dict(kw)

    def pack_forget(self):
        self.pack_info = None

    def pack_slaves(self):
        """The children this widget currently manages with pack - in pack order."""
        return [c for c in self.children if getattr(c, "pack_info", None) is not None]

    def winfo_ismapped(self):
        return 1 if self.pack_info is not None else 0

    def pack_propagate(self, flag=True):
        self.kw["propagate"] = flag

    def grid(self, **kw):
        self.grid_info = dict(kw)

    def grid_forget(self):
        self.grid_info = None

    def place(self, **kw):
        self.kw["place"] = dict(kw)

    def columnconfigure(self, *a, **kw):
        pass

    rowconfigure = columnconfigure

    # -- events ------------------------------------------------------------- #
    def bind(self, sequence, func=None, add=None):
        self.bindings.setdefault(sequence, []).append(func)

    bind_all = bind
    bind_class = bind

    def unbind(self, sequence, funcid=None):
        self.bindings.pop(sequence, None)

    unbind_all = unbind

    def destroy(self):
        """Destroy the widget AND its children, and leave it DEAD.

        The old version only unlinked the widget from its parent, so a widget that
        had been destroyed still answered every call - and a callback poking a dead
        widget looked perfectly healthy here while raising TclError for the user.
        Two shipped crashes hid behind exactly that (``gui/labels.py::_resize`` and
        ``gui/windows.py::_save_geometry``): the handler lives on a CONTAINER that
        outlives the widget it was given, so it keeps firing after the destroy.
        """
        for child in list(self.children):
            child.destroy()
        if self.master is not None and self in self.master.children:
            self.master.children.remove(self)
        self.children = []
        self.alive = False

    def winfo_exists(self):
        """1 while the widget lives, 0 once it is destroyed.

        Explicit, because ``W.__getattr__`` answers any unknown attribute with a
        no-op returning ``None``: a guard written as ``if not w.winfo_exists()``
        would then be TRUE for every widget on the fake, and silently turn the
        code it guards off in every GUI test.
        """
        return 1 if self.alive else 0

    def winfo_children(self):
        return list(self.children)

    def winfo_width(self):
        return 700

    def winfo_height(self):
        return 400

    def winfo_reqwidth(self):
        return 200

    def winfo_reqheight(self):
        return 60

    def winfo_rootx(self):
        return 100

    def winfo_rooty(self):
        return 100

    def winfo_screenwidth(self):
        return SCREEN[0]

    def winfo_screenheight(self):
        return SCREEN[1]

    def winfo_fpixels(self, _spec="1i"):
        return DPI[0]

    def winfo_viewable(self):
        return 1

    def winfo_geometry(self):
        return "760x920+40+40"

    def winfo_containing(self, *a):
        return None

    # -- clipboard ---------------------------------------------------------- #
    def clipboard_clear(self):
        CLIPBOARD.clear()

    def clipboard_append(self, text):
        CLIPBOARD.append(text)

    def grab_current(self):
        return GRAB[0]

    def grab_set(self):
        GRAB[0] = self

    def maxsize(self, *a):
        if a:
            self.kw["maxsize"] = tuple(a)
        return self.kw.get("maxsize")

    def minsize(self, *a):
        if a:
            self.kw["minsize"] = tuple(a)
        return self.kw.get("minsize")

    def focus_set(self):
        FOCUS[0] = self

    focus_force = focus_set

    def focus_get(self):
        return FOCUS[0]

    def state(self, spec=None):
        """ttk state flags: ``state(["!active"])`` clears one, ``["active"]`` sets it.

        A Toplevel's ``state()`` is a different call (window state), so with no
        argument the Root keeps answering "normal" - see Root.state below.
        """
        for flag in spec or ():
            if str(flag).startswith("!"):
                self.states.discard(str(flag)[1:])
            else:
                self.states.add(str(flag))
        return tuple(sorted(self.states))

    def after(self, _ms, func=None, *a):
        return None                 # timers never fire on their own in the fake

    def after_idle(self, func=None, *a):
        # idle callbacks are "run once the layout settles" - in the fake the
        # layout is instant, so run them straight away (only used to scroll a
        # freshly expanded section into view)
        if callable(func):
            func(*a)
        return None

    def after_cancel(self, _job):
        return None

    def bind_class(self, widget_class, sequence, func=None, add=None):
        """Class-level binding, RECORDED - it is a behaviour, not a no-op.

        ``gui/scrollable.py`` replaces ttk's own combobox wheel binding with a
        no-op, because scrolling the page while the pointer crossed a combobox
        silently changed the selected traffic filter. Against ``__getattr__``
        that call vanished, so nothing could check the fix was still in place.
        """
        CLASS_BINDINGS[(widget_class, sequence)] = func
        return ""

    @property
    def class_bindings(self):
        return CLASS_BINDINGS

    # -- scrolling ---------------------------------------------------------- #
    # A widget that cannot say how much of it is visible cannot be asked whether
    # it has anything to scroll: `_can_scroll` unpacks `yview()` into two floats,
    # and against `__getattr__`'s no-op that raised and was swallowed, so the
    # wheel dispatcher's "is there a scrollable under the pointer" answer was
    # always False. Default (0.0, 1.0) = everything fits, like a fresh widget.
    def yview(self, *args):
        if args:
            self.scrolled.append(("yview",) + args)
            return None
        return self._yview

    def yview_scroll(self, amount, what="units"):
        self.scrolled.append(("scroll", amount, what))

    def yview_moveto(self, fraction):
        self.scrolled.append(("moveto", fraction))

    @property
    def _w(self):
        """Tk widget path. Real code passes it straight back into ``tk.call``."""
        return self._path()

    @property
    def tk(self):
        """The shared interpreter handle - every real widget points at the same one.

        Explicit, and it MUST be, for the reason spelled out above ``winfo_exists``:
        ``__getattr__`` answers an unknown attribute with a function, and a function
        has no ``.call``. Production code that reaches THROUGH this attribute
        (``root.tk.call("tk", "scaling", ...)`` in ``gui/scaling.py``) therefore blew
        up and had the failure swallowed by ``crashlog`` - so Tk font scaling never
        ran in a single GUI test, silently, for as long as the fake existed.
        """
        return INTERP

    def __getattr__(self, name):
        # A MARKER the app stamps on a widget must read as absent when it was
        # never stamped. `getattr(w, "_bnt_scroll_owner", None)` asks exactly that
        # question, and a no-op function is not None - so the wheel dispatcher
        # treated EVERY widget as an owning scroll container and resolved the
        # wheel to a function. Same trap as `winfo_exists`, one layer over: there
        # the fabricated value read as "destroyed", here as "present".
        if name.startswith("_bnt_"):
            raise AttributeError(name)

        def _f(*a, **k):
            return None
        return _f


class Interp:
    """The Tcl interpreter behind ``widget.tk``: records calls, answers the few
    that production actually reads back.

    Anything not modelled returns ``""`` - Tcl's empty result - rather than
    ``None``, because callers treat the result as a string.
    """

    def __init__(self):
        self.calls = []

    def call(self, *args):
        self.calls.append(tuple(args))
        if args[:2] == ("grab", "current"):
            holder = GRAB[0]
            return holder._path() if isinstance(holder, W) else ("" if holder is None
                                                                 else str(holder))
        return ""

    def reset(self):
        self.calls.clear()


INTERP = Interp()


class Text(W):
    """A text widget that keeps line accounting, so trimming can be tested.

    Only what the app asks of it: ``insert``/``delete``/``index``/``get``. It models
    the LINE COUNT (which is all ``index("end-1c")`` is read for - see
    ``App._append_log_line``), not full Tk index arithmetic. Before this class the
    log box was a bare ``W``, ``index()`` came back as ``None`` from ``__getattr__``,
    and the ``.split(".")`` behind it raised into ``crashlog`` on every logged line:
    the widget-side trim never ran in any test.
    """

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.lines = [""]           # a fresh Tk Text already holds its final newline

    def insert(self, _where, text):
        parts = str(text).split("\n")
        self.lines[-1] += parts[0]
        self.lines.extend(parts[1:])

    def index(self, _spec="end-1c"):
        return f"{len(self.lines)}.0"

    def delete(self, start="1.0", end=None):
        if end in (None, "end"):
            self.lines = [""]
            return
        try:
            upto = int(str(end).split(".")[0]) - int(str(start).split(".")[0])
        except (TypeError, ValueError):
            return
        if upto > 0:
            self.lines = self.lines[upto:] or [""]

    def get(self, _start="1.0", _end="end"):
        return "\n".join(self.lines)


class Root(W):
    def state(self, spec=None):
        """A toplevel's window state, not ttk flags ("normal" / "iconic")."""
        return "normal"

    def geometry(self, spec=None):
        # Tk answers a wm call on a destroyed toplevel with "bad window path
        # name", not "invalid command name" - and that is the exact message the
        # recorded _save_geometry crash carried.
        self._alive_or_raise("bad window path name")
        if spec is None:
            return self.kw.get("geometry") or self.winfo_geometry()
        self.kw["geometry"] = spec
        return None

    def minsize(self, w=None, h=None):
        self.kw["minsize"] = (w, h)

    def maxsize(self, w=None, h=None):
        self.kw["maxsize"] = (w, h)

    def title(self, text=None):
        self.kw["title"] = text

    # Recorded, not swallowed by W.__getattr__: which icon call the app makes is
    # the whole difference between a running-state icon that shows and one that
    # does not. Tk's "default" flag feeds FUTURE toplevels, so a swap made only
    # with it never reaches the window the user is looking at.
    def iconphoto(self, default=False, *images):
        self.kw.setdefault("icons", []).append(
            ("default" if default else "window", images[0] if images else None))

    def iconbitmap(self, path=None, **_kw):
        self.kw.setdefault("icons", []).append(("bitmap", path))

    def protocol(self, *a):
        return None

    def update_idletasks(self):
        return None


class Notebook(W):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._tabs = []
        self._current = 0

    def add(self, child, **kw):
        self._tabs.append(child)
        child.kw.update(kw)

    def select(self, item=None):
        if item is None:
            return self._tabs[self._current] if self._tabs else None
        if isinstance(item, int):
            if 0 <= item < len(self._tabs):
                self._current = item
        elif item in self._tabs:
            self._current = self._tabs.index(item)
        return None

    def index(self, item=None):
        if item in self._tabs:
            return self._tabs.index(item)
        return self._current

    def tabs(self):
        return tuple(self._tabs)


class Paned(W):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.panes = []

    def add(self, child, **kw):
        self.panes.append(child)

    def sashpos(self, _index, value=None):
        if value is None:
            return self.kw.get("sash", 0)
        self.kw["sash"] = value
        return value


class Menu(W):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.posted = 0
        self.entry_states = {}

    def add_command(self, **kw):
        self.commands.append(dict(kw))

    def add_radiobutton(self, **kw):
        self.commands.append(dict(kw))

    def add_separator(self, **kw):
        self.commands.append({"separator": True})

    def delete(self, _first, _last=None):
        self.commands = []          # the app always rebuilds the whole menu

    def entryconfigure(self, index, **kw):
        self.entry_states[index] = dict(kw)

    def tk_popup(self, *a):
        self.posted += 1

    def grab_release(self):
        return None


class Treeview(W):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.rows = {}
        self.tags = {}              # iid -> tags (row colouring)
        self.tag_styles = {}        # tag -> options
        self.order = []
        self.headings = {}
        self.cols = {}
        self.row_at = None          # what identify_row() reports (test hook)
        self._sel = ()

    def heading(self, col, **kw):
        self.headings.setdefault(col, {}).update(kw)

    def column(self, col, option=None, **kw):
        entry = self.cols.setdefault(col, {})
        if option is not None and not kw:
            return entry.get(option)
        entry.update(kw)
        return None

    def get_children(self, item=""):
        return tuple(self.order)

    def insert(self, _parent, index, iid=None, values=(), tags=()):
        self.rows[iid] = values
        self.tags[iid] = tuple(tags or ())
        self.order.insert(index if isinstance(index, int) else len(self.order), iid)

    def item(self, iid, key=None, values=None, tags=None):
        if tags is not None:
            self.tags[iid] = tuple(tags or ())
        if values is not None:
            self.rows[iid] = values
            return None
        return self.rows.get(iid, ())

    def tag_configure(self, tag, **options):
        self.tag_styles[tag] = options

    def move(self, iid, _parent, index):
        if iid in self.order:
            self.order.remove(iid)
            self.order.insert(index, iid)

    def delete(self, iid):
        self.rows.pop(iid, None)
        if iid in self.order:
            self.order.remove(iid)

    def identify_row(self, _y):
        return self.row_at

    def selection_set(self, *iids):
        self._sel = tuple(iids)

    def selection_remove(self, *iids):
        drop = set(iids)
        self._sel = tuple(i for i in self._sel if i not in drop)

    def selection(self):
        return self._sel

    # `yview` deliberately NOT overridden: it used to return a hard-coded
    # (0.0, 1.0), i.e. "there is never anything to scroll". A double that cannot
    # express the other variant silently voids the test that depends on it - the
    # wheel dispatcher asks exactly this question to decide whether a table keeps
    # its own wheel, and with a constant answer that branch was unreachable.
    # W.yview reads `_yview`, so a test can say how much of the table is visible.


class Font:
    def measure(self, text):
        return len(str(text)) * 7

    def metrics(self, *a):
        return 16


def install():
    """Install the fake tkinter modules into ``sys.modules``."""
    widgets = dict(Tk=Root, Toplevel=Root, Frame=W, Label=W, Canvas=W, PhotoImage=W,
                   StringVar=Var, BooleanVar=Var, IntVar=Var, DoubleVar=Var,
                   Button=W, Entry=W, Checkbutton=W, LabelFrame=W, Scrollbar=W,
                   Text=Text, Listbox=W, Menu=Menu, PanedWindow=Paned,
                   TclError=TclError)
    tk = types.ModuleType("tkinter")
    for name, value in widgets.items():
        setattr(tk, name, value)
    sys.modules["tkinter"] = tk

    ttk = types.ModuleType("tkinter.ttk")
    for name, value in dict(Frame=W, Label=W, Button=W, Combobox=W, Notebook=Notebook,
                            Checkbutton=W, Entry=W, LabelFrame=W, Scrollbar=W,
                            Treeview=Treeview, Style=W, PanedWindow=Paned,
                            Menubutton=W, Separator=W).items():
        setattr(ttk, name, value)
    sys.modules["tkinter.ttk"] = ttk
    tk.ttk = ttk

    st = types.ModuleType("tkinter.scrolledtext")
    st.ScrolledText = Text
    sys.modules["tkinter.scrolledtext"] = st

    font = types.ModuleType("tkinter.font")
    font.nametofont = lambda _name: Font()
    font.Font = lambda **kw: Font()
    sys.modules["tkinter.font"] = font

    calls = {"warning": [], "error": [], "info": [], "askyesno": [True]}
    mb = types.ModuleType("tkinter.messagebox")
    mb.showwarning = lambda title, msg=None, **k: calls["warning"].append((title, msg))
    mb.showerror = lambda title, msg=None, **k: calls["error"].append((title, msg))
    mb.showinfo = lambda title, msg=None, **k: calls["info"].append((title, msg))
    mb.askyesno = lambda title, msg=None, **k: calls["askyesno"][-1]
    mb.calls = calls
    sys.modules["tkinter.messagebox"] = mb

    fd = types.ModuleType("tkinter.filedialog")
    fd.askopenfilename = lambda *a, **k: ""
    fd.asksaveasfilename = lambda *a, **k: ""
    sys.modules["tkinter.filedialog"] = fd

    sd = types.ModuleType("tkinter.simpledialog")
    sd.askstring = lambda *a, **k: None
    sys.modules["tkinter.simpledialog"] = sd
    return tk


def walk(widget):
    """Depth-first walk over a fake widget tree."""
    yield widget
    for child in list(widget.children):
        for item in walk(child):
            yield item


def texts(widget):
    """Every user-visible string in the tree (widget texts + menu labels)."""
    out = []
    for w in walk(widget):
        value = w.kw.get("text")
        if isinstance(value, str):
            out.append(value)
        for entry in w.commands:
            if isinstance(entry.get("label"), str):
                out.append(entry["label"])
    return out


def find(widget, predicate):
    return [w for w in walk(widget) if predicate(w)]
