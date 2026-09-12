import asyncio


class EventBus:
    """向所有 SSE 订阅者广播事件。"""

    def __init__(self):
        self._subscribers = set()

    def subscribe(self):
        q = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self._subscribers.discard(q)

    async def publish(self, event, data):
        for q in list(self._subscribers):
            await q.put((event, data))
