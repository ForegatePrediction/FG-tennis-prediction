"""Bounded, paginated public Gamma feed; prices are not prediction inputs."""
import json
import urllib.parse
import urllib.request

BASE='https://gamma-api.polymarket.com/events/keyset'


def pages(closed=False,maximum=500):
    cursor=None;seen=set()
    for _ in range(maximum):
        params={'tag_id':864,'closed':str(closed).lower(),'limit':100,'order':'id','ascending':'false'}
        if cursor:params['after_cursor']=cursor
        url=BASE+'?'+urllib.parse.urlencode(params)
        request=urllib.request.Request(url,headers={'User-Agent':'ForegateTennis/1.0 free-data-refresh'})
        with urllib.request.urlopen(request,timeout=45) as response:data=json.load(response)
        rows=data['events']
        if not isinstance(rows,list):raise ValueError('Invalid Gamma feed')
        for row in rows:
            if row.get('closed') is not closed or not any(str(t['id'])=='864' for t in row.get('tags',[])):
                raise ValueError('Gamma filter mismatch')
        yield rows,url
        cursor=data.get('next_cursor')
        if not cursor:return
        if cursor in seen:raise ValueError('Repeated Gamma cursor')
        seen.add(cursor)
    raise ValueError('Gamma pagination limit reached; previous index retained')
