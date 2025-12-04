import re
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, validator
import bcrypt
import secrets
import os
import subprocess
import shutil
import requests
from pathlib import Path
from typing import Optional, Dict, Any
import json
import platform

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Configuration file path
CONFIG_PATH = Path(".env")
SETUP_COMPLETE_FLAG = Path(".setup_complete")
SETUP_STATE_PATH = Path(".setup_state.json")


class SetupState(BaseModel):
    """Track setup progress"""
    step: int = 1
    admin_configured: bool = False
    features_selected: bool = False
    apis_configured: bool = False
    tools_installed: bool = False
    selected_features: Dict[str, bool] = {}


class AdminCredentials(BaseModel):
    email: EmailStr
    password: str

    @validator('password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v


def get_setup_state() -> SetupState:
    """Load setup state from file"""
    if SETUP_STATE_PATH.exists():
        with open(SETUP_STATE_PATH) as f:
            data = json.load(f)
            return SetupState(**data)
    return SetupState()


def save_setup_state(state: SetupState):
    """Save setup state to file"""
    with open(SETUP_STATE_PATH, 'w') as f:
        json.dump(state.dict(), f, indent=2)


def check_setup_complete() -> bool:
    """Check if setup has been completed"""
    return SETUP_COMPLETE_FLAG.exists() and CONFIG_PATH.exists()


def check_dependency(command: str) -> bool:
    """Check if a command/dependency is available"""
    return shutil.which(command) is not None


def get_go_path() -> Optional[Path]:
    """Get GOPATH or default Go bin directory"""
    gopath = os.environ.get('GOPATH')
    if gopath:
        return Path(gopath) / "bin"

    home = Path.home()
    return home / "go" / "bin"


def check_go_tools() -> Dict[str, Dict[str, Any]]:
    """Check if Go tools are installed with detailed info"""
    tools = {}
    go_bin = get_go_path()

    tool_checks = {
        "subfinder": {
            "command": "subfinder",
            "package": "github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest",
            "description": "Subdomain discovery tool"
        },
        "httpx": {
            "command": "httpx-toolkit",
            "package": "github.com/projectdiscovery/httpx/cmd/httpx@latest",
            "description": "HTTP toolkit for probing"
        }
    }

    for name, info in tool_checks.items():
        is_installed = check_dependency(info["command"])
        version = None

        ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')

        if is_installed:
            try:
                result = subprocess.run(
                    [info["command"], "-version"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                raw = result.stdout.strip() or result.stderr.strip()
                cleaned = ANSI_ESCAPE_RE.sub('', raw)

                version_line = None
                for line in cleaned.splitlines():
                    if "Current Version:" in line:
                        version_line = line.split("Current Version:")[1].strip()
                        break

                version = version_line or cleaned

            except:
                version = None


        tools[name] = {
            "installed": is_installed,
            "version": version,
            "package": info["package"],
            "description": info["description"],
            "optional": info.get("optional", False),
            "path": shutil.which(info["command"]) if is_installed else None
        }

    return tools


def check_gitfive_detailed() -> Dict[str, Any]:
    """Check GitFive installation with detailed information"""
    possible_paths = [
        Path("../GitFive"),
        Path.home() / "GitFive",
        Path("/opt/GitFive"),
    ]

    for path in possible_paths:
        if path.exists():
            venv_python = path / "venv" / "bin" / "python"
            main_script = path / "main.py"

            has_venv = venv_python.exists()
            has_script = main_script.exists()

            requirements_met = False
            if has_venv and has_script:
                try:
                    result = subprocess.run(
                        [str(venv_python), "-c", "import ghunt"],
                        capture_output=True,
                        timeout=5
                    )
                    requirements_met = result.returncode == 0
                except:
                    pass

            return {
                "installed": has_venv and has_script,
                "path": str(path.absolute()),
                "venv_path": str(venv_python) if has_venv else None,
                "script_path": str(main_script) if has_script else None,
                "requirements_met": requirements_met,
                "status": "ready" if (has_venv and has_script and requirements_met) else "incomplete"
            }

    return {
        "installed": False,
        "path": None,
        "venv_path": None,
        "script_path": None,
        "requirements_met": False,
        "status": "not_found"
    }


def check_python_packages() -> Dict[str, bool]:
    """Check if required Python packages are installed"""
    packages = {
        "fastapi": "Web framework",
        "uvicorn": "ASGI server",
        "jinja2": "Template engine",
        "python-multipart": "Form data handling",
        "pydantic": "Data validation",
        "bcrypt": "Password hashing",
        "python-jose": "JWT handling",
        "requests": "HTTP client",
        "aiohttp": "Async HTTP client"
    }

    results = {}
    for package, description in packages.items():
        try:
            __import__(package.replace("-", "_"))
            results[package] = {"installed": True, "description": description}
        except ImportError:
            results[package] = {"installed": False, "description": description}

    return results


def validate_hacker_target_api(api_key: str) -> Dict[str, Any]:
    """Validate HackerTarget API key with actual request"""
    try:
        response = requests.get(
            f"https://api.hackertarget.com/findshareddns/?q=google.com&apikey={api_key}",
            timeout=10
        )

        if response.status_code == 200 and "error" not in response.text.lower():
            return {
                "valid": True,
                "message": "API key is valid and working",
                "remaining_calls": response.headers.get('X-Ratelimit-Remaining', 'Unknown')
            }
        elif "error" in response.text.lower():
            return {"valid": False, "message": f"API Error: {response.text}"}
        else:
            return {"valid": False, "message": f"HTTP {response.status_code}: Invalid API key"}
    except requests.RequestException as e:
        return {"valid": False, "message": f"Connection error: {str(e)}"}


def validate_osint_industries_api(api_key: str) -> Dict[str, Any]:
    """Validate OSINT Industries API key"""
    try:
        headers = {"api-key": api_key}
        response = requests.get(
            "https://api.osint.industries/misc/credits",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            data = response.text
            return {
                "valid": True,
                "message": "API key is valid",
                "credits": data
            }
        elif response.status_code == 401:
            return {"valid": False, "message": "Invalid API key"}
        else:
            return {"valid": False, "message": f"HTTP {response.status_code}"}
    except requests.RequestException as e:
        return {"valid": False, "message": f"Connection error: {str(e)}"}


def validate_whois_history_api(api_key: str) -> Dict[str, Any]:
    """Validate WhoisXML API key"""
    try:
        response = requests.get(
            f"https://whois-history.whoisxmlapi.com/api/v1?apiKey={api_key}&domainName=google.com&mode=purchase",
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if "error" not in data:
                return {
                    "valid": True,
                    "message": "API key is valid",
                    "credits": data.get("creditsRemaining", "Unknown")
                }
            return {"valid": False, "message": data.get("error", {}).get("message", "Unknown error")}
        else:
            return {"valid": False, "message": f"HTTP {response.status_code}"}
    except requests.RequestException as e:
        return {"valid": False, "message": f"Connection error: {str(e)}"}


def validate_securitytrails_api(api_key: str) -> Dict[str, Any]:
    """Validate SecurityTrails API key"""
    try:
        headers = {"APIKEY": api_key}
        response = requests.get(
            "https://api.securitytrails.com/v1/ping",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            return {
                "valid": True,
                "message": "API key is valid",
                "tier": data.get("message", "Unknown")
            }
        elif response.status_code == 401:
            return {"valid": False, "message": "Invalid API key"}
        else:
            return {"valid": False, "message": f"HTTP {response.status_code}"}
    except requests.RequestException as e:
        return {"valid": False, "message": f"Connection error: {str(e)}"}


def validate_virustotal_api(api_key: str) -> Dict[str, Any]:
    """Validate VirusTotal API key"""
    try:
        headers = {"x-apikey": api_key}
        response = requests.get(
            "https://www.virustotal.com/api/v3/domains/google.com",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            return {"valid": True, "message": "API key is valid"}
        elif response.status_code == 401:
            return {"valid": False, "message": "Invalid API key"}
        elif response.status_code == 403:
            return {"valid": False, "message": "API key lacks required permissions"}
        else:
            return {"valid": False, "message": f"HTTP {response.status_code}"}
    except requests.RequestException as e:
        return {"valid": False, "message": f"Connection error: {str(e)}"}


def validate_api_key(service: str, api_key: str) -> Dict[str, Any]:
    validators = {
        "hacker_target": validate_hacker_target_api,
        "osint_industries": validate_osint_industries_api,
        "whois_history": validate_whois_history_api,
        "securitytrails": validate_securitytrails_api,
        "virustotal": validate_virustotal_api
    }

    validator = validators.get(service)
    if not validator:
        return {"valid": False, "message": "Unknown service"}

    try:
        return validator(api_key)
    except Exception as e:
        return {"valid": False, "message": f"Validation error: {str(e)}"}


def save_env_config(config: Dict[str, str]):
    """Save configuration to .env file"""
    env_content = []

    for key, value in config.items():
        if value:
            env_content.append(f"{key}={value}")

    with open(CONFIG_PATH, "w") as f:
        f.write("\n".join(env_content))


def install_go_tool(tool_name: str, package: str) -> Dict[str, Any]:
    """Install a single Go tool with detailed logging"""
    try:
        # Check if Go is installed
        if not check_dependency("go"):
            return {
                "success": False,
                "message": "Go is not installed",
                "install_url": "https://golang.org/dl/"
            }

        # Get Go version
        go_version = subprocess.run(
            ["go", "version"],
            capture_output=True,
            text=True
        ).stdout.strip()

        # Install the tool
        process = subprocess.Popen(
            ["go", "install", "-v", package],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        output = []
        for line in process.stdout:
            output.append(line.strip())

        process.wait()

        if process.returncode == 0:
            # Verify installation
            tool_path = shutil.which(tool_name)
            if tool_path:
                return {
                    "success": True,
                    "message": f"Successfully installed {tool_name}",
                    "path": tool_path,
                    "output": "\n".join(output)
                }
            else:
                go_bin = get_go_path()
                return {
                    "success": True,
                    "message": f"Installed but not in PATH. Add {go_bin} to your PATH",
                    "path": str(go_bin / tool_name),
                    "output": "\n".join(output)
                }
        else:
            return {
                "success": False,
                "message": f"Installation failed with exit code {process.returncode}",
                "output": "\n".join(output)
            }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error installing {tool_name}: {str(e)}"
        }


def install_go_tools() -> Dict[str, Any]:
    """Install all required Go tools"""
    if not check_dependency("go"):
        return {
            "success": False,
            "message": "Go is not installed. Please install Go first.",
            "install_url": "https://golang.org/dl/"
        }

    tools = {
        "subfinder": "github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest",
        "httpx": "github.com/projectdiscovery/httpx/cmd/httpx@latest",
    }

    results = {}
    for tool, package in tools.items():
        results[tool] = install_go_tool(tool, package)

    all_success = all(r.get("success", False) for r in results.values())

    return {
        "success": all_success,
        "results": results,
        "go_bin_path": str(get_go_path())
    }


def setup_gitfive_guide() -> Dict[str, Any]:
    """Provide detailed GitFive setup instructions"""
    return {
        "steps": [
            {
                "number": 1,
                "title": "Clone GitFive Repository",
                "command": "git clone https://github.com/mxrch/GitFive",
                "description": "Clone the official GitFive repository"
            },
            {
                "number": 2,
                "title": "Navigate to Directory",
                "command": "cd GitFive",
                "description": "Enter the GitFive directory"
            },
            {
                "number": 3,
                "title": "Create Virtual Environment",
                "command": "python -m venv venv",
                "description": "Create an isolated Python environment"
            },
            {
                "number": 4,
                "title": "Activate Virtual Environment",
                "command": "source venv/bin/activate" if platform.system() != "Windows" else "venv\\Scripts\\activate",
                "description": "Activate the virtual environment"
            },
            {
                "number": 5,
                "title": "Install Dependencies",
                "command": "pip install -r requirements.txt",
                "description": "Install all required Python packages"
            },
            {
                "number": 6,
                "title": "Login to GitHub",
                "command": "python main.py login",
                "description": "Authenticate with GitHub (use a secondary account)"
            }
        ],
        "warnings": [
            "Do not use your main GitHub account",
            "Keep your credentials secure",
            "GitFive requires authentication for full functionality"
        ]
    }


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    try:
        """Main setup page"""
        # if check_setup_complete():
            # return RedirectResponse(url="/setup/complete")

        print("Setup page")
        state = get_setup_state()

        # Get comprehensive system status
        system_status = {
            "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
            "platform": platform.system(),
            "go_installed": check_dependency("go"),
            "go_version": None,
            "go_tools": check_go_tools(),
            "gitfive": check_gitfive_detailed(),
            "python_packages": check_python_packages(),
            "go_bin_path": str(get_go_path())
        }

        if system_status["go_installed"]:
            try:
                result = subprocess.run(
                    ["go", "version"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                system_status["go_version"] = result.stdout.strip()
            except:
                pass

        return templates.TemplateResponse(
            "setup.html",
            {
                "request": request,
                "step": state.step,
                "system_status": system_status,
                "state": state.dict()
            }
        )
    except Exception as e:
        print(e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/setup/admin")
async def setup_admin(
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Configure admin credentials with enhanced validation"""
    try:
        if password != confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")

        # Validate credentials with enhanced rules
        creds = AdminCredentials(email=email, password=password)

        # Hash password with bcrypt
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))

        # Generate secure JWT secret
        jwt_secret = secrets.token_urlsafe(32)

        # Save to config
        config = {
            "ROOT_EMAIL": email,
            "ROOT_PASSWORD": hashed.decode(),
            "JWT_SECRET": jwt_secret
        }

        # Read existing config if it exists
        existing_config = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        key, val = line.strip().split("=", 1)
                        existing_config[key] = val

        # Merge configs
        existing_config.update(config)
        save_env_config(existing_config)

        # Update setup state
        state = get_setup_state()
        state.admin_configured = True
        state.step = 2
        save_setup_state(state)

        return JSONResponse({
            "success": True,
            "message": "Admin credentials configured securely",
            "next_step": 2
        })

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Configuration failed: {str(e)}")


@router.post("/setup/features")
async def setup_features(
    enable_github: bool = Form(False),
    enable_dns_recon: bool = Form(False),
    enable_ns_lookup: bool = Form(False),
    enable_osint_industries: bool = Form(False),
    enable_whois: bool = Form(False),
    enable_cavalier: bool = Form(False),
    enable_doxbin: bool = Form(False)
):
    """Configure which features to enable"""
    features = {
        "ENABLE_GITHUB": str(enable_github),
        "ENABLE_DNS_RECON": str(enable_dns_recon),
        "ENABLE_NS_LOOKUP": str(enable_ns_lookup),
        "ENABLE_OSINT_INDUSTRIES": str(enable_osint_industries),
        "ENABLE_WHOIS": str(enable_whois),
        "ENABLE_CAVALIER": str(enable_cavalier),
        "ENABLE_DOXBIN": str(enable_doxbin)
    }

    # Read existing config
    existing_config = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, val = line.strip().split("=", 1)
                    existing_config[key] = val

    # Merge configs
    existing_config.update(features)
    save_env_config(existing_config)

    # Update setup state
    state = get_setup_state()
    state.features_selected = True
    state.selected_features = {
        "github": enable_github,
        "dns_recon": enable_dns_recon,
        "ns_lookup": enable_ns_lookup,
        "osint_industries": enable_osint_industries,
        "whois": enable_whois,
        "cavalier": enable_cavalier,
        "doxbin": enable_doxbin
    }
    state.step = 3
    save_setup_state(state)

    return JSONResponse({
        "success": True,
        "message": "Features configured successfully",
        "next_step": 3,
        "selected_count": sum([enable_github, enable_dns_recon, enable_ns_lookup,
                               enable_osint_industries, enable_whois, enable_cavalier, enable_doxbin])
    })


@router.post("/setup/apis")
async def setup_apis(
    hacker_target: Optional[str] = Form(None),
    osint_industries: Optional[str] = Form(None),
    whois_history: Optional[str] = Form(None),
    securitytrails: Optional[str] = Form(None),
    virustotal: Optional[str] = Form(None),
    gitfive_venv: Optional[str] = Form(None),
    gitfive_script: Optional[str] = Form(None)
):
    """Configure API keys with validation"""
    api_config = {}

    if hacker_target:
        api_config["HACKER_TARGET_API_KEY"] = hacker_target.strip()
    if osint_industries:
        api_config["OSINT_INDUSTRIES_API_KEY"] = osint_industries.strip()
    if whois_history:
        api_config["WHOIS_HISTORY_API_KEY"] = whois_history.strip()
    if securitytrails:
        api_config["SECURITYTRAILS_API_KEY"] = securitytrails.strip()
    if virustotal:
        api_config["VIRUSTOTAL_API_KEY"] = virustotal.strip()
    if gitfive_venv:
        api_config["GITFIVE_VENV_PATH"] = gitfive_venv.strip()
    if gitfive_script:
        api_config["GITFIVE_SCRIPT_PATH"] = gitfive_script.strip()

    # Read existing config
    existing_config = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, val = line.strip().split("=", 1)
                    existing_config[key] = val

    # Merge configs
    existing_config.update(api_config)
    save_env_config(existing_config)

    # Update setup state
    state = get_setup_state()
    state.apis_configured = True
    state.step = 4
    save_setup_state(state)

    return JSONResponse({
        "success": True,
        "message": f"Configured {len(api_config)} API keys",
        "next_step": 4,
        "configured_count": len(api_config)
    })


@router.post("/setup/install-tools")
async def install_tools():
    """Install Go tools automatically with detailed progress"""
    if not check_dependency("go"):
        raise HTTPException(
            status_code=400,
            detail="Go is not installed. Please install Go first from https://golang.org/dl/"
        )

    results = install_go_tools()

    # Update setup state
    state = get_setup_state()
    state.tools_installed = results["success"]
    save_setup_state(state)

    return JSONResponse(results)


@router.post("/setup/validate-api")
async def validate_api(
    service: str = Form(...),
    api_key: str = Form(...)
):
    """Validate an API key with actual service check"""
    if not api_key or not api_key.strip():
        return JSONResponse({
            "valid": False,
            "message": "API key cannot be empty"
        })

    result = validate_api_key(service, api_key.strip())
    return JSONResponse(result)


@router.get("/setup/gitfive-guide")
async def gitfive_guide():
    """Get detailed GitFive setup instructions"""
    guide = setup_gitfive_guide()
    gitfive_status = check_gitfive_detailed()

    return JSONResponse({
        "guide": guide,
        "status": gitfive_status
    })


@router.get("/setup/system-check")
async def system_check():
    """Comprehensive system status check"""
    return JSONResponse({
        "python": {
            "version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
            "executable": os.sys.executable,
            "packages": check_python_packages()
        },
        "go": {
            "installed": check_dependency("go"),
            "path": shutil.which("go"),
            "tools": check_go_tools(),
            "bin_path": str(get_go_path())
        },
        "gitfive": check_gitfive_detailed(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine()
        }
    })


@router.post("/setup/complete")
async def complete_setup():
    """Mark setup as complete"""
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=400, detail="Configuration not found")

    state = get_setup_state()
    if not state.admin_configured:
        raise HTTPException(status_code=400, detail="Admin account not configured")

    # Create completion flag
    SETUP_COMPLETE_FLAG.touch()

    # Final state update
    state.step = 5
    save_setup_state(state)

    return JSONResponse({
        "success": True,
        "message": "Setup completed successfully! Redirecting...",
        "redirect": "/",
        "summary": {
            "admin_configured": state.admin_configured,
            "features_selected": state.features_selected,
            "apis_configured": state.apis_configured,
            "tools_installed": state.tools_installed
        }
    })


@router.get("/setup/complete", response_class=HTMLResponse)
async def setup_complete_page(request: Request):
    """Setup completion page"""
    state = get_setup_state()
    return templates.TemplateResponse(
        "setup_complete.html",
        {
            "request": request,
            "state": state.dict()
        }
    )


@router.get("/setup/status")
async def setup_status():
    """Get current setup status"""
    state = get_setup_state()
    return JSONResponse({
        "setup_complete": check_setup_complete(),
        "config_exists": CONFIG_PATH.exists(),
        "state": state.dict(),
        "system_status": {
            "go_installed": check_dependency("go"),
            "go_tools": check_go_tools(),
            "gitfive": check_gitfive_detailed()
        }
    })


@router.post("/setup/reset")
async def reset_setup(confirm: str = Form(...)):
    """Reset setup (for development/testing)"""
    if confirm != "RESET":
        raise HTTPException(status_code=400, detail="Invalid confirmation")

    if SETUP_COMPLETE_FLAG.exists():
        SETUP_COMPLETE_FLAG.unlink()

    if SETUP_STATE_PATH.exists():
        SETUP_STATE_PATH.unlink()

    return JSONResponse({
        "success": True,
        "message": "Setup reset successfully. You can now run setup again."
    })