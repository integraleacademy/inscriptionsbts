def post_worker_init(worker):
    # Start the daily reader also on idle WSGI instances, after a potential preload/fork.
    for name in ("cyclades_start", "akto_start", "opco_start"):
        start = getattr(worker.wsgi, "extensions", {}).get(name)
        if start:
            start()
