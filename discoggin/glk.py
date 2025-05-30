import os, os.path
import json
import logging

def get_glkstate_for_session(app, session):
    """Load the GlkState for a session, or None if the session is not
    running.
    """
    path = os.path.join(app.autosavedir, session.autosave, 'glkstate.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fl:
            obj = json.load(fl)
        return GlkState.from_jsonable(obj)
    except Exception as ex:
        logging.error('get_glkstate: %s', ex, exc_info=ex)
        return None

def put_glkstate_for_session(app, session, state):
    """Store the GlkState for a session, or delete it if state is None.
    This assumes the session directory exists. (Unless state is None,
    in which case it's okay if there is nothing to delete!)
    """
    path = os.path.join(app.autosavedir, session.autosave, 'glkstate.json')
    if not state:
        if os.path.exists(path):
            os.remove(path)
    else:
        obj = state.to_jsonable()
        with open(path, 'w') as fl:
            json.dump(obj, fl)

class GlkState:
    _singleton_keys = [ 'generation', 'lineinputwin', 'charinputwin', 'specialinput', 'hyperlinkinputwin' ]
    _contentlist_keys = [ 'statuswindat', 'storywindat', 'graphicswindat' ]
    
    def __init__(self):
        # Lists of ContentLines
        self.statuswindat = []
        self.storywindat = []
        self.graphicswindat = []
        # Gotta keep track of where each status window begins in the
        # (vertically) agglomerated statuswin[] array
        self.statuslinestarts = {}
        self.windows = {}
        # This doesn't track multiple-window input the way it should,
        # nor distinguish hyperlink input state across multiple windows.
        self.lineinputwin = None
        self.charinputwin = None
        self.specialinput = None
        self.hyperlinkinputwin = None
        self.generation = 0

    def to_jsonable(self):
        """Turn a GlkState into a jsonable dict. We use this for
        serialization.
        Note that the contents of a GlkState are not immutable. So
        you shouldn't hold onto the object returned by this call;
        serialize it immediately and discard it.
        """
        obj = {}
        for key in GlkState._singleton_keys:
            obj[key] = getattr(self, key)
        for key in GlkState._contentlist_keys:
            arr = getattr(self, key)
            obj[key] = [ dat.to_jsonable() for dat in arr ]
        obj['statuslinestarts'] = strkeydict(self.statuslinestarts)
        obj['windows'] = strkeydict(self.windows)
        return obj

    @staticmethod
    def from_jsonable(obj):
        """Create a GlkState from a jsonable object (from to_jsonable).
        """
        state = GlkState()
        for key in GlkState._singleton_keys:
            setattr(state, key, obj[key])
        for key in GlkState._contentlist_keys:
            ls = [ ContentLine.from_jsonable(val) for val in obj[key] ]
            setattr(state, key, ls)
        state.statuslinestarts = intkeydict(obj['statuslinestarts'])
        state.windows = intkeydict(obj['windows'])
        return state
    
    def accept_update(self, update, extrainput=None):
        """Parse the GlkOte update object and update the state
        accordingly.
        This is complicated. For the format, see
        http://eblong.com/zarf/glk/glkote/docs.html
        """
        self.generation = update.get('gen')

        windows = update.get('windows')
        if windows is not None:
            self.windows = {}
            for win in windows:
                id = win.get('id')
                self.windows[id] = win
            
            grids = [ win for win in self.windows.values() if win.get('type') == 'grid' ]
            totalheight = 0
            # This doesn't work if just one status window resizes.
            # We should be keeping track of them separately and merging
            # the lists on every update.
            self.statuslinestarts.clear()
            for win in grids:
                self.statuslinestarts[win.get('id')] = totalheight
                totalheight += win.get('gridheight', 0)
            if totalheight < len(self.statuswindat):
                self.statuswindat = self.statuswindat[0:totalheight]
            while totalheight > len(self.statuswindat):
                self.statuswindat.append(ContentLine())

        contents = update.get('content')
        if contents is not None:
            for content in contents:
                id = content.get('id')
                win = self.windows.get(id)
                if not win:
                    raise Exception('No such window')
                if win.get('type') == 'buffer':
                    text = content.get('text')
                    # Clear the buffer. But if the content starts with
                    # append, preserve the last line.
                    willappend = ((text and text[0].get('append'))
                                  or (extrainput is not None))
                    if willappend and self.storywindat:
                        self.storywindat = [ self.storywindat[-1] ]
                    else:
                        self.storywindat = []
                    if extrainput is not None:
                        dat = ContentLine(extrainput, 'input')
                        if len(self.storywindat):
                            self.storywindat[-1].extend(dat)
                        else:
                            self.storywindat.append(dat)
                        self.storywindat.append(ContentLine())
                    if text:
                        for line in text:
                            dat = extract_raw(line)
                            if line.get('append') and len(self.storywindat):
                                self.storywindat[-1].extend(dat)
                            else:
                                self.storywindat.append(dat)
                elif win.get('type') == 'grid':
                    lines = content.get('lines')
                    for line in lines:
                        linenum = self.statuslinestarts[id] + line.get('line')
                        dat = extract_raw(line)
                        if linenum >= 0 and linenum < len(self.statuswindat):
                            self.statuswindat[linenum] = dat
                elif win.get('type') == 'graphics':
                    self.graphicswin = []
                    self.graphicswindat = []
                    draw = content.get('draw')
                    if draw:
                        self.graphicswindat.append([draw])

        inputs = update.get('input')
        specialinputs = update.get('specialinput')
        if specialinputs is not None:
            self.specialinput = specialinputs.get('type')
            if self.specialinput == 'fileref_prompt':
                inptype = specialinputs.get('filetype', '???')
                inpmode = specialinputs.get('filemode', '???')
                val = 'Enter %s filename to %s:' % (inptype, inpmode,)
                self.storywindat.append(ContentLine(val))
                self.storywindat.append(ContentLine('>>'))
            self.lineinputwin = None
            self.charinputwin = None
            self.hyperlinkinputwin = None
            #self.mouseinputwin = None
        elif inputs is not None:
            self.specialinput = None
            self.lineinputwin = None
            self.charinputwin = None
            self.hyperlinkinputwin = None
            #self.mouseinputwin = None
            for input in inputs:
                if input.get('type') == 'line':
                    if self.lineinputwin:
                        raise Exception('Multiple windows accepting line input')
                    self.lineinputwin = input.get('id')
                if input.get('type') == 'char':
                    if self.charinputwin:
                        raise Exception('Multiple windows accepting char input')
                    self.charinputwin = input.get('id')
                if input.get('hyperlink'):
                    self.hyperlinkinputwin = input.get('id')
                #if input.get('mouse'):
                #    self.mouseinputwin = input.get('id')

    def construct_input(self, cmd, savefiledir):
        """Given a player command string, construct a GlkOte input
        appropriate to what the game is expecting.
        TODO: If the game is expecting more than one kind of input
        (e.g. line+hypertext or line+timer), allow the player to
        specify both.
        """
        if self.lineinputwin:
            return {
                'type':'line', 'gen':self.generation,
                'window':self.lineinputwin, 'value':cmd
            }
        if self.charinputwin:
            ### adjust cmd for special cases? arrow keys?
            return {
                'type':'char', 'gen':self.generation,
                'window':self.charinputwin, 'value':cmd
            }
        if self.specialinput == 'fileref_prompt':
            path = os.path.join(savefiledir, sanitize_filename(cmd))
            return {
                'type':'specialresponse', 'gen':self.generation,
                'response':'fileref_prompt', 'value':path
            }
        raise Exception('game is not expecting input')

def strkeydict(map):
    return dict([ (str(key), val) for (key, val) in map.items() ])
    
def intkeydict(map):
    return dict([ (int(key), val) for (key, val) in map.items() ])
    
class ContentLine:
    def __init__(self, text=None, style='normal'):
        self.arr = []
        if text is not None:
            self.add(text, style)

    def __repr__(self):
        return 'C:'+repr(self.arr)

    def to_jsonable(self):
        return self.arr

    @staticmethod
    def from_jsonable(arr):
        dat = ContentLine()
        dat.arr = arr
        return dat

    def add(self, text='', style='normal', link=None):
        if link:
            self.arr.append( (text, style, link) )
        elif style and style != 'normal':
            self.arr.append( (text, style) )
        else:
            self.arr.append( (text,) )

    def extend(self, dat):
        self.arr.extend(dat.arr)
                
def extract_raw(line):
    # Extract the content array from a GlkOte line object.
    res = ContentLine()
    con = line.get('content')
    if not con:
        return res
    for val in con:
        if type(val) == str:
            res.add(val)
        else:
            res.add(val.get('text', ''), val.get('style', 'normal'))
            ### hyperlink
    return res

def sanitize_filename(val):
    return val ###

def create_metrics(width=None, height=None):
    if not width:
        width = 800
    if not height:
        height = 480
    res = {
        'width':width, 'height':height,
        'gridcharwidth':10, 'gridcharheight':12,
        'buffercharwidth':10, 'buffercharheight':12,
    }
    return res
