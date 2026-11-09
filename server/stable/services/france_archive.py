"""将已保存的可见表格无损转成解析器输入；不补造来源没有的字段。"""
from html import escape
from .race_data_source_adapters import canonical_sha
from .france_sources import geny_key


class ArchivedPage(str):
    """raw_sha256 绑定原始可见文档 JSON，而不是转码后的 HTML。"""
    pass


def replay_page(document, *, observed_at):
    key=geny_key(document['url'])
    title=escape(document['title'])
    body='<p>'+escape(document.get('text',''))+'</p>'
    if key[4]=='partants-pronostics':
        body+='<table>'+''.join('<tr>'+''.join('<td>'+escape(cell)+'</td>' for cell in row)+'</tr>' for row in document['rows'])+'</table>'
    else:
        body+=''.join('<div class="h-10 flex-row"><div>'+escape(row['rank'])+'</div><div>'+
            ''.join('<div dir="auto">'+escape(cell)+'</div>' for cell in row['leaves'])+'</div></div>' for row in document['rows'])
    # 原始采集未记录浏览器时区，因此不注入 source-timezone，不猜发走时间。
    page=ArchivedPage('<html><head><title>'+title+'</title></head><body>'+body+'</body></html>')
    page.raw_sha256=canonical_sha(document)
    page.observed_at=observed_at
    return page
