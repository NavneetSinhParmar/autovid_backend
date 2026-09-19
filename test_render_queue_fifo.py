import asyncio

from app.services.render_queue import enqueue_render_job, get_render_job, start_render_worker


async def main():
    start_order: list[int] = []
    complete_order: list[int] = []

    start_render_worker()

    async def enqueue_one(i: int):
        async def work(job_id: str, output_path: str, folder: str):
            start_order.append(i)
            await asyncio.sleep(0.05)
            complete_order.append(i)

        return enqueue_render_job(kind=f"fifo_test_{i}", extension="mp4", work=work)

    jobs = await asyncio.gather(*(enqueue_one(i) for i in range(1, 6)))

    while True:
        statuses = [get_render_job(job["job_id"])["status"] for job in jobs]
        if all(status in ("completed", "failed") for status in statuses):
            break
        await asyncio.sleep(0.02)

    assert start_order == [1, 2, 3, 4, 5], start_order
    assert complete_order == [1, 2, 3, 4, 5], complete_order

    print("queued job_ids:", [job["job_id"] for job in jobs])
    print("processing order:", start_order)
    print("completion order:", complete_order)


if __name__ == "__main__":
    asyncio.run(main())
