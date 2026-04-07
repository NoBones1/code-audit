import hashlib
import os

def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()  # MD5 for passwords is broken

def run_user_command(user_input):
    result = eval(user_input)  # code injection via eval
    return result

def aggregate_logs(log_dir):
    all_entries = []
    for fname in os.listdir(log_dir):
        with open(os.path.join(log_dir, fname)) as f:
            for line in f:
                all_entries.append(line)  # unbounded memory growth
    return all_entries

def process_and_report(data, output_path, config, db, logger, mailer):
    """Does way too many things: validates, transforms, persists, emails, logs."""
    validated = []
    for item in data:
        if item.get("value") and item["value"] > 0:
            validated.append(item)
    transformed = [{"id": v["id"], "amount": v["value"] * 1.08} for v in validated]
    for t in transformed:
        db.insert("reports", t)
    logger.info(f"Processed {len(transformed)} items")
    with open(output_path, "w") as f:
        import json
        json.dump(transformed, f)
    if len(transformed) > 100:
        mailer.send("admin@example.com", f"Large batch: {len(transformed)} items")
    return transformed
