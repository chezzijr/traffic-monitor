import asyncio

# uvloop chỉ tồn tại trên Linux
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    print("uvloop enabled")
except Exception:
    print("uvloop not available, using default asyncio loop")

from service.collector import run_loop

if __name__ == "__main__":
    asyncio.run(run_loop())
