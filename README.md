# EaseSpace Web Application

<div align="center">

**[ภาษาไทย](#-ภาษาไทย) | [English](#-english)**

</div>

---

## 🇹🇭 ภาษาไทย

### สารบัญ
- [เกี่ยวกับโปรเจกต์](#เกี่ยวกับโปรเจกต์)
- [สิ่งที่ต้องเตรียมก่อนเริ่มต้น](#สิ่งที่ต้องเตรียมก่อนเริ่มต้น)
- [การติดตั้ง](#การติดตั้ง)
  - [1. ดาวน์โหลดซอร์สโค้ด](#1-ดาวน์โหลดซอร์สโค้ด)
  - [2. ตั้งค่าไฟล์ Environment](#2-ตั้งค่าไฟล์-environment-env)
  - [3. ติดตั้งโมเดล AI](#3-ดาวน์โหลดและติดตั้งโมเดล-ai-สำเร็จรูป)
- [การรันเซิร์ฟเวอร์](#การรันเซิร์ฟเวอร์)
  - [1. สร้าง Virtual Environment](#1-สร้างและเปิดใช้งาน-virtual-environment)
  - [2. ติดตั้งแพ็กเกจ](#2-ติดตั้งแพ็กเกจและไลบรารีที่จำเป็น)
  - [3. รันเซิร์ฟเวอร์](#3-รันเซิร์ฟเวอร์จำลองเพื่อทดสอบระบบ)
  - [4. เข้าใช้งานเว็บไซต์](#4-การเข้าใช้งานเว็บไซต์)

---

### เกี่ยวกับโปรเจกต์

ซอร์สโค้ดสำหรับระบบเว็บไซต์หลักของ EaseSpace ซึ่งทำหน้าที่เป็นส่วนของ Frontend และรับส่งข้อมูลกับฐานข้อมูล รวมถึงประมวลผลการวิเคราะห์อารมณ์ร่วมกับโมเดลปัญญาประดิษฐ์

---

### สิ่งที่ต้องเตรียมก่อนเริ่มต้น

1. โปรแกรม **Visual Studio Code**
2. **Python 3.10** หรือเวอร์ชันที่สูงกว่า
3. **ไฟล์ Private Key (`.json`)** จาก Firebase
4. **ค่า firebaseConfig** และ **Gemini API Key**

---

### การติดตั้ง

#### 1. ดาวน์โหลดซอร์สโค้ด

เปิด Terminal หรือ Command Prompt แล้วรันคำสั่ง

```cmd
git clone https://github.com/Pathanink/easespace-webapp.git
```

จากนั้นเข้าสู่โฟลเดอร์โปรเจกต์

```cmd
cd easespace-webapp
```

#### 2. ตั้งค่าไฟล์ Environment (`.env`)

- นำไฟล์ Private Key `.json` มาวางไว้ในโฟลเดอร์หลักของโปรเจกต์
- คัดลอกไฟล์ `.env.example` แล้วเปลี่ยนชื่อเป็น `.env`
- เปิดไฟล์ `.env` และนำค่า `firebaseConfig` ชื่อไฟล์ `.json` และคีย์ `Gemini API` มากรอกลงในตัวแปรให้ครบถ้วนและถูกต้อง

#### 3. ดาวน์โหลดและติดตั้งโมเดล AI สำเร็จรูป

> **หมายเหตุ:** ข้ามขั้นตอนนี้ได้ หากคุณได้ทำการเทรนโมเดลเองและนำโฟลเดอร์ `final_model` มาวางไว้แล้ว

- สร้างโฟลเดอร์ใหม่ชื่อ `final_model` ไว้ในระดับเดียวกับไฟล์ `app.py`
- เข้าไปดาวน์โหลดไฟล์โมเดลทั้งหมดจาก [Hugging Face Repository](https://huggingface.co/Pathanink/easespace-wangchanberta/tree/main)
- นำไฟล์ที่ดาวน์โหลดมาทั้งหมดไปวางไว้ในโฟลเดอร์ `final_model`

---

### การรันเซิร์ฟเวอร์

#### 1. สร้างและเปิดใช้งาน Virtual Environment

เปิดหน้าต่าง Terminal ใน Visual Studio Code (ตั้งค่าประเภทเป็น Command Prompt) และรันคำสั่งต่อไปนี้

```cmd
python -m venv venv
```

```cmd
venv\Scripts\activate
```

> เมื่อเปิดใช้งานสำเร็จ จะเห็นคำว่า `(venv)` ขึ้นนำหน้าบรรทัดคำสั่ง

#### 2. ติดตั้งแพ็กเกจและไลบรารีที่จำเป็น

```cmd
pip install -r requirements.txt
```

> รอจนกว่าระบบจะดาวน์โหลดและติดตั้งเสร็จสิ้น

#### 3. รันเซิร์ฟเวอร์จำลองเพื่อทดสอบระบบ

ตรวจสอบให้แน่ใจว่าไฟล์ `.env` และโฟลเดอร์โมเดลถูกจัดวางเรียบร้อยแล้ว จากนั้นรันคำสั่ง

```cmd
python app.py
```

#### 4. การเข้าใช้งานเว็บไซต์

เมื่อระบบประมวลผลเสร็จสิ้น จะแสดงข้อความยืนยัน เช่น `Running on http://127.0.0.1:5000`

- เปิดเว็บเบราว์เซอร์ แล้วพิมพ์ URL `http://localhost:5000` หรือ `http://127.0.0.1:5000`
- หรือกดปุ่ม `Ctrl` ค้างไว้แล้วคลิกที่ลิงก์ใน Terminal เพื่อเปิดหน้าเว็บแอปพลิเคชันได้ทันที

---

<br>

## 🇬🇧 English

### Table of Contents
- [About](#about)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Configure Environment File](#2-configure-environment-file-env)
  - [3. Install AI Model](#3-download-and-install-the-pre-built-ai-model)
- [Running the Server](#running-the-server)
  - [1. Create Virtual Environment](#1-create-and-activate-virtual-environment)
  - [2. Install Dependencies](#2-install-required-packages-and-libraries)
  - [3. Start the Server](#3-run-the-development-server)
  - [4. Access the Web App](#4-accessing-the-web-application)

---

### About

Source code for the main EaseSpace web application, serving as the Frontend layer, handling database communication, and processing emotion analysis in conjunction with an AI model.

---

### Prerequisites

1. **Visual Studio Code**
2. **Python 3.10** or higher
3. **Firebase Private Key file (`.json`)**
4. **firebaseConfig values** and a **Gemini API Key**

---

### Installation

#### 1. Clone the Repository

Open a Terminal or Command Prompt and run:

```cmd
git clone https://github.com/Pathanink/easespace-webapp.git
```

Then navigate into the project folder:

```cmd
cd easespace-webapp
```

#### 2. Configure Environment File (`.env`)

- Place the Firebase Private Key `.json` file in the root directory of the project.
- Copy `.env.example` and rename it to `.env`.
- Open the `.env` file and fill in the `firebaseConfig` values, the `.json` filename, and the `Gemini API` key.

#### 3. Download and Install the Pre-built AI Model

> **Note:** Skip this step if you have already trained the model yourself and placed the `final_model` folder in the project.

- Create a new folder named `final_model` at the same level as `app.py`.
- Download all model files from the [Hugging Face Repository](https://huggingface.co/Pathanink/easespace-wangchanberta/tree/main).
- Place all downloaded files inside the `final_model` folder.

---

### Running the Server

#### 1. Create and Activate Virtual Environment

Open a Terminal in Visual Studio Code (set the terminal type to **Command Prompt**) and run the following commands:

```cmd
python -m venv venv
```

```cmd
venv\Scripts\activate
```

> Once activated successfully, you will see `(venv)` at the beginning of the command line.

#### 2. Install Required Packages and Libraries

```cmd
pip install -r requirements.txt
```

> Wait for all packages to finish downloading and installing.

#### 3. Run the Development Server

Make sure the `.env` file and the model folder are correctly placed, then run:

```cmd
python app.py
```

#### 4. Accessing the Web Application

Once the server is ready, a confirmation message such as `Running on http://127.0.0.1:5000` will appear.

- Open a web browser and navigate to `http://localhost:5000` or `http://127.0.0.1:5000`
- Or hold `Ctrl` and click the link in the Terminal to open the web application directly.
