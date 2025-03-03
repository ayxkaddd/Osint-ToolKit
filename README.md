# OSINT Toolkit

A modern web interface for various OSINT tools and resources. Built with FastAPI, TailwindCSS, and a focus on user experience.

## Preview

![image](https://github.com/user-attachments/assets/faf405e4-f0c8-43ba-95cf-bcea0469bcfc)


## Features

- **GitHub Analysis**: Deep dive into GitHub profiles using GitFive
- **DNS Lookup**: Find shared nameservers and domain relationships
- **OSINT Industries Integration**: Search for emails, phones, and usernames
- **Cavalier API**: Search for compromised accounts and data
- **DoxBin Search**: Search the breached DoxBin database
- **WHOIS History**: Research domain registration history
- **External Resources**: Curated list of useful OSINT tools and websites

## Installation

1. Clone the repository:
```bash
git clone https://github.com/ayxkaddd/Osint-ToolKit
cd Osint-ToolKit
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the project and its dependencies:
```bash
pip install .
```

4. Create a `.env` file with your configuration:
```env
JWT_SECRET=your_jwt_secret_key
ROOT_EMAIL=your_email@example.com
ROOT_PASSWORD=your_password_encrypted_with_bcrypt
```
5. Follow the instructions below to setup the modules

# Modules Setup

## 1. GitHub Analysis (GitFive)

1. Clone the GitFive repository:
```bash
git clone https://github.com/mxrch/GitFive
cd GitFive
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate
```

3. Install the project and its dependencies:
```bash
pip install -r requirements.txt
```

4. Add GitFive paths to your `.env`:
```env
GITFIVE_VENV_PATH=/path/to/GitFive/venv/bin/python
GITFIVE_SCRIPT_PATH=/path/to/GitFive/main.py
```

### Usage:
1. Navigate to /git in the web interface
2. Enter a GitHub username
3. View detailed analysis including:
   - Repository statistics
   - SSH keys
   - Email addresses
   - Username history
   - Related accounts


## 2. NS Lookup

1. Get a HackerTarget API key from hackertarget.com
2. Add the API key to your `.env`:
```env
HACKER_TARGET_API_KEY=your_api_key
```

### Usage:
1. Navigate to /ns in the web interface
2. Enter two nameservers (e.g. kelly.ns.cloudflare.com and sean.ns.cloudflare.com)
3. View domains sharing the same nameservers
4. Click `Analyze WHOIS Records` button to find connections between domains


## 3. OSINT Industries

1. Get your API key from osint.industries
3. Add to .env:
```env
OSINT_INDUSTRIES_API_KEY=your_api_key
```

### Usage:
1. Navigate to /osint in the web interface
2. Enter an email, phone number, or username
3. View Pdf report of results from various OSINT sources


## 4. WHOIS History
1. Get API key from whoisxmlapi.com (up to 1,000 free API requests)
2. Add to .env:
```env
WHOIS_HISTORY_API_KEY=your_api_key
```

### Usage:
1. Navigate to /whois in the web interface
2. Enter domain name
3. View historical WHOIS records and changes


#### The rest of the modules do not require any setup


## Start using OSINT Toolkit

1. Start the FastAPI server:
```bash
uvicorn main:app --reload
```

2. Open your browser and navigate to `http://localhost:8000`

3. Login with the credentials you set in the `.env` file

4. You can change module settings in the web interface

5. Enjoy!

## Project Structure

- `/assets`: Static files and cached results
- `/models`: Pydantic models for data validation
- `/routes`: API route handlers
- `/services`: Business logic and external service integrations
- `/templates`: HTML templates using TailwindCSS
