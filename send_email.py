import requests

NTFY_TOPIC = "autoResearch-BrowserAgent"

def send_experiment_email(subject, body):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"{subject}\n\n{body}".encode("utf-8"),
            headers={"Title": subject}
        )
        print(f"Notification sent: {subject}")
    except Exception as e:
        print(f"Notification failed: {e}")

if __name__ == "__main__":
    send_experiment_email(
        "Test - pre-auth autoresearch",
        "Notifications working on DO droplet!"
    )