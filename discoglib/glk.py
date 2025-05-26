
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
