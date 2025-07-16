# aws-manager


## Web Interface (Django)

This repository includes a Django project located in the `webapp/` directory. It
provides a modern web interface styled with Bootstrap and integrates with AWS
IAM Identity Center (SSO) for authentication.

To run the development server:

```bash
pip install -r requirements.txt
cd webapp
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser and you will see the home page
with navigation and search features for AWS resources.

### Logging in

Both the command line tool (`aws-manager.py`) and the web interface rely on AWS
CLI v2 and an SSO profile. When you initiate an SSO login (either by running the
script or by submitting the web login form with **SSO** selected), the command
`aws sso login` is executed. This opens the AWS SSO authentication page in your
default browser; after you complete the sign-in, the application retrieves the
access token and grants access to the search features.
