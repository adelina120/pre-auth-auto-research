import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_experiment_email(subject, body):
    gmail_user = "rkk.bme@gmail.com"
    gmail_password = "vuponvhjyjbkzkni"
    
    recipients = [
        "rkk.bme@gmail.com",
        "adelinanie120@gmail.com"
    ]
    
    msg = MIMEMultipart()
    msg['From'] = gmail_user
    msg['To'] = ", ".join(recipients)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())
        server.quit()
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email failed: {e}")