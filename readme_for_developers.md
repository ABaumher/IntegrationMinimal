## About the Code Here

This is going to assume you have some knowledge of python, but maybe not asynchronous code or more specifically asyncio. The first thing to note is that, perhaps counterintuitively, async does not mean that the code is running at the same time. This concept is known as concurrency, and they are not the same. Whenever you see an await, it is merely telling the hardware that whatever 