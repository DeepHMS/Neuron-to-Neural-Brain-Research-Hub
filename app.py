import os
import json
import random
import string
import requests
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import gspread
import feedparser

app = FastAPI(title="Neuron to Neural - Bharat Brain Research Hub")

# -----------------------------------------------------------------------------
# Google Sheets Setup
# -----------------------------------------------------------------------------
def get_gspread_client():
    try:
        secret_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
        if not secret_json:
            return None
        creds_dict = json.loads(secret_json)
        return gspread.service_account_from_dict(creds_dict)
    except Exception as e:
        print(f"GSpread Error: {e}")
        return None

# -----------------------------------------------------------------------------
# Pydantic Schemas & Globals
# -----------------------------------------------------------------------------
class UserAuth(BaseModel):
    name: str
    institution: str
    country: str
    email: str

class OTPRequest(BaseModel):
    name: str
    email: str

class VerifyOTP(UserAuth):
    otp: str

class AdminLogin(BaseModel):
    username: str
    password: str

class SubmissionData(BaseModel):
    submitter_name: str
    submitter_email: str
    main_category: str  # NUE-Hub or NRI Directory
    sub_category: str   # Tool type or NRI type
    payload: Dict[str, Any]

class AdminAction(BaseModel):
    req_id: str
    action: str  # approve, decline, approve_modified
    modified_payload: Optional[Dict[str, Any]] = None

otp_store = {}

# Email Helper
def send_email_via_webhook(to_email: str, subject: str, body: str):
    script_url = os.environ.get("GOOGLE_SCRIPT_URL")
    if not script_url:
        print(f"[Email Skipped] To: {to_email} | Subj: {subject}\n{body}")
        return
    try:
        requests.post(script_url, json={"to": to_email, "subject": subject, "body": body})
    except Exception as e:
        print(f"Failed to send email: {e}")

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------
@app.post("/api/send-otp")
async def send_otp(req: OTPRequest):
    otp = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    otp_store[req.email] = otp
    
    body = f"Hello {req.name},\n\nYour secure access code for the Neuron to Neural Hub is:\n\n{otp}\n\nThis code will expire shortly."
    send_email_via_webhook(req.email, "Neuron to Neural - Access Code", body)
    return {"status": "success"}

@app.post("/api/verify-otp")
async def verify_otp_and_login(data: VerifyOTP):
    if otp_store.get(data.email) != data.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired Access Code.")
    del otp_store[data.email]
    
    client = get_gspread_client()
    if client:
        try:
            sheet = client.open("Neuron2Neural_DB").worksheet("Users")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.append_row([timestamp, data.name, data.institution, data.country, data.email])
        except Exception:
            pass
    return {"status": "success", "email": data.email, "role": "user"}

@app.post("/api/admin-login")
async def admin_login(data: AdminLogin):
    if data.username == "N2Nhead" and data.password == "N2N1234??":
        return {"status": "success", "role": "admin"}
    raise HTTPException(status_code=403, detail="Invalid credentials")

@app.post("/api/submit-data")
async def submit_data(data: SubmissionData):
    req_id = str(uuid.uuid4())[:8].upper()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    client = get_gspread_client()
    if client:
        try:
            sheet = client.open("Neuron2Neural_DB").worksheet("Pending_Submissions")
            sheet.append_row([
                req_id, timestamp, data.submitter_email, data.submitter_name, 
                data.main_category, data.sub_category, json.dumps(data.payload)
            ])
            
            body = f"Hello {data.submitter_name},\n\nThank you for submitting to the Neuron to Neural Hub.\nYour request number is: {req_id}.\n\nThe Admin will check the information, and you will receive a notification once it is approved and added to the platform."
            send_email_via_webhook(data.submitter_email, f"Submission Received [{req_id}]", body)
        except Exception as e:
            print(f"Submit error: {e}")
            raise HTTPException(status_code=500, detail="Failed to save submission.")
            
    return {"status": "success", "req_id": req_id}

@app.get("/api/admin/pending")
async def get_pending():
    client = get_gspread_client()
    if not client: return {"requests": []}
    try:
        sheet = client.open("Neuron2Neural_DB").worksheet("Pending_Submissions")
        records = sheet.get_all_records()
        return {"requests": records}
    except Exception:
        return {"requests": []}

@app.post("/api/admin/action")
async def process_admin_action(data: AdminAction):
    client = get_gspread_client()
    if not client: raise HTTPException(status_code=500, detail="DB Error")
    
    try:
        db = client.open("Neuron2Neural_DB")
        pending_sheet = db.worksheet("Pending_Submissions")
        records = pending_sheet.get_all_records()
        
        target_row_idx = None
        target_record = None
        for idx, row in enumerate(records):
            if str(row.get("req_id", row.get("ID", ""))) == data.req_id:
                target_row_idx = idx + 2 
                target_record = row
                break
                
        if not target_record:
            raise HTTPException(status_code=404, detail="Request not found")
            
        submitter_email = target_record.get("submitter_email", "")
        payload_to_save = data.modified_payload if data.action == "approve_modified" else json.loads(target_record["payload"])
        
        if data.action in ["approve", "approve_modified"]:
            target_sheet_name = "Tools" if target_record["main_category"] == "NUE-Hub" else "NRI"
            target_sheet = db.worksheet(target_sheet_name)
            
            row_data = [datetime.now().strftime("%Y-%m-%d")] + list(payload_to_save.values())
            target_sheet.append_row(row_data)
            
            body = f"Hello,\n\nYour submission [{data.req_id}] has been approved and added! Please check the Neuron to Neural (Bharat Brain Research Hub) platform to view your entry."
            send_email_via_webhook(submitter_email, f"Submission Approved [{data.req_id}]", body)
            
        elif data.action == "decline":
            body = f"Hello,\n\nUnfortunately, we have to decline your submission [{data.req_id}] as the inputs were not correct, all information was not added properly, or there was a mismatch. Please review and submit again."
            send_email_via_webhook(submitter_email, f"Submission Declined [{data.req_id}]", body)
            
        pending_sheet.delete_rows(target_row_idx)
        return {"status": "success"}
        
    except Exception as e:
        print(f"Action error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/data/journals")
async def get_journals():
    client = get_gspread_client()
    if client:
        try:
            sheet = client.open("Neuron2Neural_DB").worksheet("Journals")
            records = sheet.get_all_records()
            return {"journals": records}
        except Exception:
            pass
    return {"journals": []}

@app.get("/api/data/{category}")
async def get_data(category: str):
    client = get_gspread_client()
    sheet_name = "Tools" if category == "tools" else "NRI"
    if client:
        try:
            sheet = client.open("Neuron2Neural_DB").worksheet(sheet_name)
            records = sheet.get_all_records()
            return {"data": records}
        except Exception:
            pass
    return {"data": []}

@app.get("/api/news")
async def get_news():
    try:
        feed = feedparser.parse("https://news.yahoo.com/rss/science")
        articles = [{"title": e.title, "link": e.link, "published": getattr(e, 'published', 'Recently'), "source": "Yahoo Science"} for e in feed.entries[:8]]
        return {"articles": articles}
    except Exception:
        return {"articles": []}

# -----------------------------------------------------------------------------
# Frontend HTML String
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html_content = """
<!DOCTYPE html>
<html lang="en" class="h-full bg-slate-900 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Neuron to Neural | Bharat Brain Research Hub</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        .loader { border-top-color: #6366f1; animation: spinner 1.5s linear infinite; }
        @keyframes spinner { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body class="h-full flex flex-col font-sans antialiased selection:bg-indigo-500 selection:text-white">

    <!-- Auth Modal -->
    <div id="authModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
        <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 sm:p-8 max-w-md w-full shadow-2xl relative my-8">
            <div class="absolute top-4 right-4 flex space-x-2">
                <button onclick="toggleAdminAuth(false)" id="tabUserAuth" class="text-xs text-indigo-400 font-bold px-2 py-1 bg-indigo-900/30 rounded border border-indigo-500/30">User Login</button>
                <button onclick="toggleAdminAuth(true)" id="tabAdminAuth" class="text-xs text-slate-400 font-bold px-2 py-1 rounded hover:text-white transition">Admin Login</button>
            </div>
            
            <div class="text-center mb-6 mt-4">
                <div class="w-12 h-12 bg-indigo-600/20 text-indigo-400 rounded-full flex items-center justify-center mx-auto mb-3 text-2xl">🧠</div>
                <h2 class="text-2xl font-bold text-white">Neuron to Neural</h2>
                <p class="text-xs text-indigo-400 font-medium tracking-wide uppercase mt-1">Bharat Brain Research Hub</p>
            </div>
            
            <!-- User Form -->
            <div id="userAuthSection">
                <form id="detailsForm" class="space-y-4">
                    <div><label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Full Name *</label><input type="text" id="userName" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-indigo-500"></div>
                    <div><label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Institution / Company *</label><input type="text" id="userInst" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-indigo-500"></div>
                    <div class="grid grid-cols-2 gap-3">
                        <div><label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Country *</label><input type="text" id="userCountry" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-indigo-500"></div>
                        <div><label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Valid Email *</label><input type="email" id="userEmail" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-indigo-500"></div>
                    </div>
                    <div class="flex items-start gap-2 pt-2">
                        <input type="checkbox" id="userAgree" required class="mt-1 rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-indigo-500">
                        <label for="userAgree" class="text-xs text-slate-400 leading-snug">I agree to the processing of my information for platform access.</label>
                    </div>
                    <button type="button" id="requestOtpBtn" onclick="requestOTP(event)" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-2.5 rounded-lg text-sm transition">Request Access Code</button>
                </form>

                <form id="otpForm" onsubmit="event.preventDefault(); verifyOTP(event);" class="space-y-4 hidden">
                    <div class="text-center mb-4 bg-indigo-900/20 border border-indigo-500/20 p-3 rounded-lg">
                        <p class="text-xs text-slate-300 leading-relaxed">An access code has been sent to your email <strong id="displayEmail" class="text-indigo-400"></strong>. Please check your spam folder.</p>
                    </div>
                    <div><input type="text" id="userOtp" required maxlength="6" placeholder="ENTER 6-DIGIT CODE" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-3 text-lg text-center tracking-[0.5em] font-mono text-white focus:border-indigo-500"></div>
                    <button type="submit" id="verifyOtpBtn" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-2.5 rounded-lg text-sm transition">Verify & Enter</button>
                    
                    <div class="flex justify-between items-center mt-3 border-t border-slate-700 pt-3">
                        <button type="button" onclick="backToDetails()" class="text-xs text-slate-400 hover:text-white transition">← Wrong Email ID?</button>
                        <button type="button" id="resendBtn" onclick="resendOTP()" disabled class="text-xs text-indigo-400 disabled:text-slate-500 transition">Resend Code (60s)</button>
                    </div>
                </form>
            </div>

            <!-- Admin Form -->
            <div id="adminAuthSection" class="hidden">
                <form id="adminForm" onsubmit="event.preventDefault(); loginAdmin(event);" class="space-y-4">
                    <div><label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Admin Username</label><input type="text" id="adminUser" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-amber-500"></div>
                    <div><label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Admin Password</label><input type="password" id="adminPass" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-amber-500"></div>
                    <button type="submit" class="w-full bg-amber-600 hover:bg-amber-500 text-white font-semibold py-2.5 rounded-lg text-sm transition mt-4">Login as Admin</button>
                </form>
            </div>
        </div>
    </div>

    <!-- Header -->
    <header class="bg-slate-800/80 backdrop-blur border-b border-slate-700 sticky top-0 z-30">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex items-center justify-between h-16">
                <div class="flex items-center space-x-3">
                    <span class="text-3xl">🧠</span>
                    <div>
                        <h1 class="text-lg font-bold text-white leading-tight">Neuron to Neural</h1>
                        <p class="text-xs text-indigo-400 font-medium hidden sm:block">Bharat Brain Research Hub</p>
                    </div>
                </div>
                <div class="flex items-center space-x-2">
                    <span id="userBadge" class="hidden sm:inline-block text-xs bg-slate-700 text-slate-300 px-3 py-1 rounded-full border border-slate-600"></span>
                    <button id="submitBtn" onclick="openSubmitModal()" class="hidden bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-3 py-1.5 rounded-full font-semibold transition"><i class="fa-solid fa-cloud-arrow-up mr-1"></i> Upload/Submit Data</button>
                    <button id="adminPanelBtn" onclick="openAdminPanel()" class="hidden bg-amber-600 hover:bg-amber-500 text-white text-xs px-3 py-1.5 rounded-full font-semibold transition"><i class="fa-solid fa-lock mr-1"></i> Admin Panel</button>
                    <button id="logoutBtn" onclick="logoutUser()" class="hidden bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs px-3 py-1.5 rounded-full font-semibold transition"><i class="fa-solid fa-sign-out-alt"></i></button>
                </div>
            </div>
            
            <nav class="flex space-x-1 sm:space-x-4 border-t border-slate-700/50 overflow-x-auto py-2 text-xs sm:text-sm">
                <button onclick="switchTab('nue')" id="tab-nue" class="tab-btn px-4 py-2 rounded-lg font-medium whitespace-nowrap">NUE-Hub</button>
                <button onclick="switchTab('nri')" id="tab-nri" class="tab-btn px-4 py-2 rounded-lg font-medium whitespace-nowrap">NRI Directory</button>
                <button onclick="switchTab('journals')" id="tab-journals" class="tab-btn px-4 py-2 rounded-lg font-medium whitespace-nowrap">Neuroscience Journals</button>
                <button onclick="switchTab('gnn')" id="tab-gnn" class="tab-btn px-4 py-2 rounded-lg font-medium whitespace-nowrap">Global News</button>
            </nav>
        </div>
    </header>

    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <section id="section-nue" class="tab-content space-y-6">
            <h2 class="text-xl font-bold text-white mb-2 border-b border-slate-700 pb-2">NUE-Hub (Tools)</h2>
            <div id="toolsGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"></div>
        </section>

        <section id="section-nri" class="tab-content hidden space-y-6">
            <h2 class="text-xl font-bold text-white mb-2 border-b border-slate-700 pb-2">NRI Directory</h2>
            <div id="nriGrid" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
        </section>

        <section id="section-journals" class="tab-content hidden space-y-6">
            <div class="flex flex-col md:flex-row gap-4 bg-slate-800/50 p-4 rounded-xl border border-slate-700/60">
                <select id="journalSearchHeader" class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-300 w-full md:w-48">
                    <option value="Journal title">Journal Title</option>
                    <option value="Keywords">Keywords</option>
                    <option value="Publisher">Publisher</option>
                    <option value="Subjects">Subjects</option>
                </select>
                <div class="relative w-full">
                    <i class="fa-solid fa-search absolute left-3 top-3 text-slate-400 text-sm"></i>
                    <input type="text" id="journalSearchText" oninput="filterJournalsRealtime()" placeholder="Search journals by partial string..." class="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm focus:border-indigo-500 text-white">
                </div>
            </div>
            <div class="overflow-x-auto bg-slate-800 rounded-xl border border-slate-700">
                <table class="min-w-full text-left text-sm text-slate-300">
                    <thead class="bg-slate-900/50 text-xs uppercase text-slate-400 border-b border-slate-700">
                        <tr><th class="px-4 py-3">Title</th><th class="px-4 py-3">Publisher</th><th class="px-4 py-3">Keywords</th><th class="px-4 py-3">APC</th></tr>
                    </thead>
                    <tbody id="journalsTableBody" class="divide-y divide-slate-700/50"></tbody>
                </table>
            </div>
        </section>

        <section id="section-gnn" class="tab-content hidden space-y-6">
            <h2 class="text-xl font-bold text-white mb-2 border-b border-slate-700 pb-2">Global News</h2>
            <div id="newsGrid" class="space-y-3"></div>
        </section>
    </main>

    <!-- Submission Modal -->
    <div id="submitModal" class="hidden fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
        <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 max-w-2xl w-full my-8 relative">
            <button onclick="document.getElementById('submitModal').classList.add('hidden')" class="absolute top-4 right-4 text-slate-400 hover:text-white"><i class="fa-solid fa-times text-xl"></i></button>
            <h3 class="text-xl font-bold text-white mb-4">Upload / Submit Data</h3>
            
            <form id="submissionForm" onsubmit="event.preventDefault(); handleDataSubmit(event);" class="space-y-4">
                <div class="grid grid-cols-2 gap-4">
                    <div><label class="block text-xs text-slate-400 mb-1">Submitter Name</label><input type="text" id="subName" readonly class="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-500"></div>
                    <div><label class="block text-xs text-slate-400 mb-1">Submitter Email</label><input type="email" id="subEmail" readonly class="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-500"></div>
                </div>

                <div>
                    <label class="block text-xs font-semibold text-slate-300 uppercase mb-1">Main Category</label>
                    <select id="mainCat" onchange="renderDynamicForm()" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-indigo-500">
                        <option value="">Select Category...</option>
                        <option value="NUE-Hub">NUE-Hub (Tools/Software)</option>
                        <option value="NRI Directory">NRI Directory (People/Centers)</option>
                    </select>
                </div>
                
                <div id="dynamicFormArea" class="space-y-4 border-t border-slate-700 pt-4 mt-4 hidden"></div>

                <div class="bg-indigo-900/20 border border-indigo-500/20 p-3 rounded-lg flex gap-3 items-start">
                    <i class="fa-solid fa-info-circle text-indigo-400 mt-0.5"></i>
                    <p class="text-xs text-slate-300">The information will be verified by the Admin and will be approved before being added to the public website. You will receive an email confirmation.</p>
                </div>

                <button type="submit" id="finalSubmitBtn" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-2.5 rounded-lg text-sm transition hidden">Submit Request</button>
            </form>
        </div>
    </div>

    <!-- Admin Dashboard Modal -->
    <div id="adminPanelModal" class="hidden fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
        <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 w-full max-w-6xl h-[90vh] flex flex-col">
            <div class="flex justify-between items-center mb-4 pb-4 border-b border-slate-700">
                <h3 class="text-xl font-bold text-amber-400"><i class="fa-solid fa-lock mr-2"></i>Admin Dashboard</h3>
                <button onclick="document.getElementById('adminPanelModal').classList.add('hidden')" class="text-slate-400 hover:text-white"><i class="fa-solid fa-times text-xl"></i></button>
            </div>
            
            <div class="flex-1 overflow-auto">
                <h4 class="text-white font-semibold mb-3">Pending Submissions</h4>
                <div class="overflow-x-auto bg-slate-900 rounded-xl border border-slate-700">
                    <table class="min-w-full text-left text-sm text-slate-300">
                        <thead class="bg-slate-800 text-xs uppercase text-slate-400">
                            <tr><th class="px-4 py-3">ID</th><th class="px-4 py-3">User</th><th class="px-4 py-3">Category</th><th class="px-4 py-3">Details (JSON)</th><th class="px-4 py-3 text-right">Actions</th></tr>
                        </thead>
                        <tbody id="adminTableBody" class="divide-y divide-slate-700/50"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- Scripts -->
    <script>
        let currentUser = null;
        let pendingUser = null;
        let resendTimer = null;
        let resendCount = 0;
        let allJournals = [];
        
        const topicsList = ["Neurodegenerative Disease", "Neurooncology", "NeuroOmics", "Molecular & Cellular Neuroscience", "Neuroimmunology & Neuroinflammation", "Systems Neuroscience", "Sensory & Motor Neuroscience", "Neuroendocrinology", "Neurodevelopment", "Gut-Brain Axis & Enteric Neuroscience", "Cognitive Neuroscience", "Behavioral Neuroscience", "Affective Neuroscience", "Sleep & Circadian Neuroscience", "Neuroengineering & Neuroprosthetics", "Computational Neuroscience", "Neuroimaging & Brain Connectomics", "Neuropharmacology", "Neurovascular & Stroke Research", "Translational & Regenerative Neuroscience", "AI for Neuroscience", "Neurosurgery"];
        const statesList = ["Andhra Pradesh","Arunachal Pradesh","Assam","Bihar","Chhattisgarh","Goa","Gujarat","Haryana","Himachal Pradesh","Jharkhand","Karnataka","Kerala","Madhya Pradesh","Maharashtra","Manipur","Meghalaya","Mizoram","Nagaland","Odisha","Punjab","Rajasthan","Sikkim","Tamil Nadu","Telangana","Tripura","Uttar Pradesh","Uttarakhand","West Bengal"];

        window.addEventListener('DOMContentLoaded', () => {
            const savedUser = localStorage.getItem('n2n_user');
            if (savedUser) {
                currentUser = JSON.parse(savedUser);
                document.getElementById('authModal').classList.add('hidden');
                setupUserUI();
            }
            fetchData('tools');
            fetchData('nri');
            fetchJournals();
            fetchNews();
            switchTab('nue');
        });

        function toggleAdminAuth(showAdmin) {
            const userSec = document.getElementById('userAuthSection');
            const adminSec = document.getElementById('adminAuthSection');
            const tabUser = document.getElementById('tabUserAuth');
            const tabAdmin = document.getElementById('tabAdminAuth');

            if (showAdmin) {
                userSec.classList.add('hidden');
                adminSec.classList.remove('hidden');
                tabAdmin.className = 'text-xs text-amber-400 font-bold px-2 py-1 bg-amber-900/30 rounded border border-amber-500/30';
                tabUser.className = 'text-xs text-slate-400 font-bold px-2 py-1 rounded hover:text-white transition';
            } else {
                userSec.classList.remove('hidden');
                adminSec.classList.add('hidden');
                tabAdmin.className = 'text-xs text-slate-400 font-bold px-2 py-1 rounded hover:text-white transition';
                tabUser.className = 'text-xs text-indigo-400 font-bold px-2 py-1 bg-indigo-900/30 rounded border border-indigo-500/30';
            }
        }

        async function requestOTP(e, isResend = false) {
            if(e) e.preventDefault();
            
            try {
                if(!isResend) {
                    const form = document.getElementById('detailsForm');
                    
                    // Force the browser to show what field is missing
                    if (!form.checkValidity()) {
                        form.reportValidity();
                        return;
                    }
                    
                    pendingUser = {
                        name: document.getElementById('userName').value,
                        institution: document.getElementById('userInst').value,
                        country: document.getElementById('userCountry').value,
                        email: document.getElementById('userEmail').value
                    };
                }
                
                const btn = document.getElementById('requestOtpBtn');
                btn.innerText = "Sending Code..."; 
                btn.disabled = true;

                const res = await fetch('/api/send-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: pendingUser.name, email: pendingUser.email })
                });

                if (!res.ok) {
                    throw new Error("Server returned status: " + res.status);
                }

                if(!isResend) {
                    document.getElementById('detailsForm').classList.add('hidden');
                    document.getElementById('otpForm').classList.remove('hidden');
                    document.getElementById('displayEmail').innerText = pendingUser.email;
                    startResendTimer();
                } else {
                    alert("New code sent!");
                }
                
                btn.innerText = "Request Access Code"; 
                btn.disabled = false;
                
            } catch (error) {
                console.error("OTP Error:", error);
                alert("Request failed. Please check your network or try again later.");
                const btn = document.getElementById('requestOtpBtn');
                btn.innerText = "Request Access Code"; 
                btn.disabled = false;
            }
        }

        function startResendTimer() {
            let timeLeft = 60;
            const btn = document.getElementById('resendBtn');
            btn.disabled = true;
            clearInterval(resendTimer);
            resendTimer = setInterval(() => {
                timeLeft--;
                if(timeLeft <= 0) {
                    clearInterval(resendTimer);
                    if(resendCount === 0) {
                        btn.innerText = "Resend Code";
                        btn.disabled = false;
                    } else {
                        btn.innerText = "Resend Limit Reached";
                    }
                } else {
                    btn.innerText = `Resend Code (${timeLeft}s)`;
                }
            }, 1000);
        }

        function resendOTP() {
            resendCount++;
            document.getElementById('resendBtn').disabled = true;
            requestOTP(null, true);
        }

        async function verifyOTP(e) {
            e.preventDefault();
            const btn = document.getElementById('verifyOtpBtn');
            btn.innerText = "Verifying...";
            
            const otpCode = document.getElementById('userOtp').value.toUpperCase();
            const payload = { ...pendingUser, otp: otpCode };
            const res = await fetch('/api/verify-otp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });

            if (res.ok) {
                const data = await res.json();
                currentUser = { ...pendingUser, role: data.role };
                finishLogin();
            } else {
                alert("Invalid or Expired Code.");
                btn.innerText = "Verify & Enter";
            }
        }

        async function loginAdmin(e) {
            e.preventDefault();
            const payload = { username: document.getElementById('adminUser').value, password: document.getElementById('adminPass').value };
            const res = await fetch('/api/admin-login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            if(res.ok) {
                currentUser = { name: "Admin", email: "admin@neuron2neural.org", role: "admin" };
                finishLogin();
            } else { alert("Invalid Admin Credentials"); }
        }

        function finishLogin() {
            localStorage.setItem('n2n_user', JSON.stringify(currentUser));
            document.getElementById('authModal').classList.add('hidden');
            setupUserUI();
        }

        function backToDetails() {
            clearInterval(resendTimer);
            document.getElementById('otpForm').classList.add('hidden');
            document.getElementById('detailsForm').classList.remove('hidden');
        }

        function logoutUser() {
            localStorage.removeItem('n2n_user');
            location.reload();
        }

        function setupUserUI() {
            if (!currentUser) return;
            document.getElementById('userBadge').innerText = currentUser.name;
            document.getElementById('userBadge').classList.remove('hidden');
            document.getElementById('logoutBtn').classList.remove('hidden');
            
            if (currentUser.role === 'admin') {
                document.getElementById('adminPanelBtn').classList.remove('hidden');
            } else {
                document.getElementById('submitBtn').classList.remove('hidden');
            }
        }

        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('.tab-btn').forEach(el => {
                el.classList.remove('bg-indigo-600', 'text-white');
                el.classList.add('text-slate-300');
            });
            document.getElementById(`section-${tabId}`).classList.remove('hidden');
            const activeBtn = document.getElementById(`tab-${tabId}`);
            activeBtn.classList.add('bg-indigo-600', 'text-white');
            activeBtn.classList.remove('text-slate-300');
        }

        // --- DYNAMIC FORM LOGIC ---
        function openSubmitModal() {
            document.getElementById('submitModal').classList.remove('hidden');
            document.getElementById('subName').value = currentUser.name;
            document.getElementById('subEmail').value = currentUser.email;
            document.getElementById('mainCat').value = "";
            document.getElementById('dynamicFormArea').innerHTML = "";
            document.getElementById('dynamicFormArea').classList.add('hidden');
            document.getElementById('finalSubmitBtn').classList.add('hidden');
        }

        function renderDynamicForm() {
            const cat = document.getElementById('mainCat').value;
            const area = document.getElementById('dynamicFormArea');
            area.innerHTML = "";
            if(!cat) { area.classList.add('hidden'); document.getElementById('finalSubmitBtn').classList.add('hidden'); return; }
            
            let html = "";
            if(cat === "NUE-Hub") {
                html += `
                    <select id="subCat" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                        <option value="">Select Category</option><option>Omics</option><option>Structural Mapping</option><option>Digital Health</option><option>EEG/ECG</option><option>MRI</option>
                    </select>
                    <input type="text" id="f_name" placeholder="Tool Name *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                    <input type="url" id="f_link" placeholder="Tool Link *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                    <input type="text" id="f_ref" placeholder="Reference (Manuscript/Github) *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                    <textarea id="f_desc" placeholder="Description (Max 50 words) *" maxlength="300" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3 h-20"></textarea>
                    <div class="grid grid-cols-2 gap-3 mb-3">
                        <input type="date" id="f_date" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-400">
                        <input type="text" id="f_dev" placeholder="Developed By *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                    </div>
                `;
            } else if (cat === "NRI Directory") {
                html += `
                    <select id="subCat" onchange="renderNRISubForm()" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                        <option value="">Select NRI Type</option><option>Researchers</option><option>Scientist & Clinicians</option><option>Centers</option><option>Communities</option><option>Start Up & Companies</option>
                    </select>
                    <div id="nriSubFormArea"></div>
                `;
            }
            area.innerHTML = html;
            area.classList.remove('hidden');
            if(cat === "NUE-Hub") document.getElementById('finalSubmitBtn').classList.remove('hidden');
        }

        function renderNRISubForm() {
            const sub = document.getElementById('subCat').value;
            const area = document.getElementById('nriSubFormArea');
            area.innerHTML = "";
            let html = "";
            const topicOpts = topicsList.map(t => `<option value="${t}">${t}</option>`).join('');
            
            if(sub === "Researchers" || sub === "Scientist & Clinicians") {
                const posOpts = sub === "Researchers" ? `<option>Masters</option><option>JRF</option><option>SRF</option><option>Ph.D.</option><option>Research Associate (RA)</option><option>Post-Doctoral Fellow</option>` : `<option>Assistant Prof.</option><option>Associate Prof.</option><option>Professor</option><option>Scientist</option><option>Clinicians</option>`;
                html += `
                    <div class="grid grid-cols-3 gap-3 mb-3">
                        <select id="f_title" required class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"><option>Mr.</option><option>Ms.</option><option>Mrs.</option><option>Dr.</option></select>
                        <input type="text" id="f_fname" placeholder="First Name *" required class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                        <input type="text" id="f_lname" placeholder="Last Name *" required class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                    </div>
                    <select id="f_pos" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3"><option value="">Select Position *</option>${posOpts}</select>
                    <select id="f_topic" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3"><option value="">Topic of Research *</option>${topicOpts}</select>
                    <input type="text" id="f_inst" placeholder="Institution *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                    <input type="url" id="f_link" placeholder="Institutional Link *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                    <div class="grid grid-cols-2 gap-3">
                        <input type="url" id="f_linkedin" placeholder="LinkedIn (Opt)" class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                        <input type="url" id="f_scholar" placeholder="Google Scholar (Opt)" class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                    </div>
                `;
            } else if (sub === "Centers") {
                const stateOpts = statesList.map(s => `<option value="${s}">${s}</option>`).join('');
                html += `
                    <input type="text" id="f_name" placeholder="Name of Center *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                    <select id="f_state" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3"><option value="">Select State *</option>${stateOpts}</select>
                    <input type="url" id="f_link" placeholder="Official Link *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                    <input type="email" id="f_email" placeholder="Official Email *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                `;
            } else if (sub === "Communities" || sub === "Start Up & Companies") {
                html += `<input type="text" id="f_name" placeholder="Name *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">`;
                if(sub === "Start Up & Companies") {
                    html += `<input type="text" id="f_founder" placeholder="Founder Name *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                             <input type="text" id="f_cin" placeholder="CIN Number *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">`;
                }
                html += `
                    <input type="url" id="f_link" placeholder="Official Link *" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3">
                    <textarea id="f_desc" placeholder="Description (< 50 words) *" maxlength="300" required class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white mb-3 h-20"></textarea>
                `;
            }
            area.innerHTML = html;
            document.getElementById('finalSubmitBtn').classList.remove('hidden');
        }

        async function handleDataSubmit(e) {
            e.preventDefault();
            const btn = document.getElementById('finalSubmitBtn');
            btn.innerText = "Submitting..."; btn.disabled = true;

            const mainCat = document.getElementById('mainCat').value;
            const subCat = document.getElementById('subCat').value;
            
            let payload = {};
            document.querySelectorAll('#dynamicFormArea input, #dynamicFormArea select, #dynamicFormArea textarea').forEach(el => {
                if(el.id && el.id.startsWith('f_')) { payload[el.id.replace('f_','')] = el.value; }
            });

            const submitData = {
                submitter_name: currentUser.name,
                submitter_email: currentUser.email,
                main_category: mainCat,
                sub_category: subCat,
                payload: payload
            };

            const res = await fetch('/api/submit-data', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(submitData) });
            
            if(res.ok) {
                if(confirm("Submission successful! Admin will review it.\n\nWant to submit one more?")) {
                    openSubmitModal();
                } else {
                    document.getElementById('submitModal').classList.add('hidden');
                }
            } else {
                alert("Submission failed. Please try again.");
            }
            btn.innerText = "Submit Request"; btn.disabled = false;
        }

        async function fetchData(cat) {
            const res = await fetch(`/api/data/${cat}`);
            const data = await res.json();
            if(cat === 'tools') renderTools(data.data);
            if(cat === 'nri') renderNRI(data.data);
        }

        function renderTools(tools) {
            document.getElementById('toolsGrid').innerHTML = tools.map(t => `
                <div class="bg-slate-800/80 border border-slate-700/80 p-5 rounded-xl">
                    <h3 class="font-bold text-white text-base">${t.Name || t.name || 'Unnamed Tool'}</h3>
                    <p class="text-xs text-slate-400 mt-2">${t.Description || t.desc || ''}</p>
                </div>
            `).join('');
        }

        function renderNRI(nri) {
            document.getElementById('nriGrid').innerHTML = nri.map(t => `
                <div class="bg-slate-800/60 border border-slate-700/60 p-4 rounded-xl">
                    <h4 class="text-sm font-bold text-white">${t.Name || t.fname || 'Unnamed'}</h4>
                    <p class="text-xs text-slate-400">${t.Institution || t.state || t.desc || ''}</p>
                </div>
            `).join('');
        }

        async function fetchJournals() {
            const res = await fetch('/api/data/journals');
            const data = await res.json();
            allJournals = data.journals;
            filterJournalsRealtime();
        }

        function filterJournalsRealtime() {
            const query = document.getElementById('journalSearchText').value.toLowerCase();
            const header = document.getElementById('journalSearchHeader').value;
            
            const filtered = allJournals.filter(j => {
                if(!query) return true;
                const val = j[header];
                if(typeof val === 'string') return val.toLowerCase().includes(query);
                return false;
            });

            const tbody = document.getElementById('journalsTableBody');
            tbody.innerHTML = filtered.slice(0, 100).map(j => `
                <tr>
                    <td class="px-4 py-3"><a href="${j['Journal URL'] || '#'}" target="_blank" class="text-indigo-400 hover:underline font-medium">${j['Journal title']}</a></td>
                    <td class="px-4 py-3">${j['Publisher'] || '-'}</td>
                    <td class="px-4 py-3 text-[11px] text-slate-400">${j['Keywords'] ? j['Keywords'].substring(0, 50) + '...' : '-'}</td>
                    <td class="px-4 py-3"><span class="bg-slate-700 px-2 py-1 rounded text-[10px]">${j['APC'] || 'N/A'}</span></td>
                </tr>
            `).join('');
        }

        async function fetchNews() {
            const res = await fetch('/api/news');
            const data = await res.json();
            document.getElementById('newsGrid').innerHTML = data.articles.map(a => `
                <a href="${a.link}" target="_blank" class="block bg-slate-800/40 border border-slate-700/60 p-4 rounded-xl">
                    <h4 class="text-sm font-semibold text-white">${a.title}</h4>
                    <p class="text-[11px] text-slate-500 mt-1">${a.source} • ${a.published}</p>
                </a>
            `).join('');
        }

        async function openAdminPanel() {
            document.getElementById('adminPanelModal').classList.remove('hidden');
            const res = await fetch('/api/admin/pending');
            const data = await res.json();
            
            const tbody = document.getElementById('adminTableBody');
            tbody.innerHTML = data.requests.map(r => `
                <tr>
                    <td class="px-4 py-3 font-mono text-[10px]">${r.req_id || r.ID}</td>
                    <td class="px-4 py-3 text-xs">${r.submitter_name}<br><span class="text-slate-500">${r.submitter_email}</span></td>
                    <td class="px-4 py-3 text-xs"><span class="bg-indigo-900/50 text-indigo-400 px-2 py-1 rounded">${r.main_category}</span><br>${r.sub_category}</td>
                    <td class="px-4 py-3 text-[10px] text-slate-400 max-w-xs truncate" title='${r.payload}'>${r.payload}</td>
                    <td class="px-4 py-3 text-right space-x-1">
                        <button onclick="adminAction('${r.req_id || r.ID}', 'approve')" class="bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600 hover:text-white px-2 py-1 rounded text-[10px]">Approve</button>
                        <button onclick="adminAction('${r.req_id || r.ID}', 'decline')" class="bg-red-600/20 text-red-400 hover:bg-red-600 hover:text-white px-2 py-1 rounded text-[10px]">Decline</button>
                    </td>
                </tr>
            `).join('');
        }

        async function adminAction(reqId, action) {
            if(!confirm(`Are you sure you want to ${action} this request?`)) return;
            const res = await fetch('/api/admin/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ req_id: reqId, action: action })
            });
            if(res.ok) {
                alert(`Action ${action} successful! Email sent.`);
                openAdminPanel();
            } else { alert("Action failed."); }
        }
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
