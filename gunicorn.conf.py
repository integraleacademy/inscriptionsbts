def post_worker_init(worker):
    # Start the daily reader also on idle WSGI instances, after a potential preload/fork.
    start = getattr(worker.wsgi, "extensions", {}).get("cyclades_start")
    if start:
        start()
