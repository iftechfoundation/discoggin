
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

class GlkState:
    def __init__(self):
        # Lists of line data lists
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
        
    def accept_update(self, update):
        # Parse the update object. This is complicated. For the format,
        # see http://eblong.com/zarf/glk/glkote/docs.html
        
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
                self.statuswindat.append([])

        contents = update.get('content')
        if contents is not None:
            for content in contents:
                id = content.get('id')
                win = self.windows.get(id)
                if not win:
                    raise Exception('No such window')
                if win.get('type') == 'buffer':
                    self.storywindat = []
                    text = content.get('text')
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
                            self.statuswindat[linenum].append(dat)
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

class ContentLine:
    def __init__(self):
        self.arr = []

    def __repr__(self):
        return 'C:'+repr(self.arr)

    def add(self, text='', style='normal', link=None):
        self.arr.append( (text, style, link) )

    def extend(self, dat):
        self.arr.extend(dat.arr)
                
def extract_raw(line):
    # Extract the content array from a line object.
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

