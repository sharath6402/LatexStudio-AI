// Injects Firebase web config into firebase-init.js from environment
// variables at build time, so the real values never need to be committed to
// the (public) repo. Set these as Vercel Project Settings -> Environment
// Variables, and set the Vercel Build Command to `node build.js`.
const fs = require("fs");
const path = require("path");

const FIELD_ENV = {
    apiKey: "FIREBASE_API_KEY",
    authDomain: "FIREBASE_AUTH_DOMAIN",
    projectId: "FIREBASE_PROJECT_ID",
    storageBucket: "FIREBASE_STORAGE_BUCKET",
    messagingSenderId: "FIREBASE_MESSAGING_SENDER_ID",
    appId: "FIREBASE_APP_ID",
};
const OPTIONAL_FIELD_ENV = {
    measurementId: "FIREBASE_MEASUREMENT_ID",
};

const missing = Object.values(FIELD_ENV).filter((envVar) => !process.env[envVar]);
if (missing.length) {
    console.error(`Missing required Firebase env vars: ${missing.join(", ")}`);
    process.exit(1);
}

const filePath = path.join(__dirname, "firebase-init.js");
let content = fs.readFileSync(filePath, "utf8");

function setField(content, field, value) {
    const re = new RegExp(`(${field}:\\s*")[^"]*(")`);
    return content.replace(re, `$1${value}$2`);
}

for (const [field, envVar] of Object.entries(FIELD_ENV)) {
    content = setField(content, field, process.env[envVar]);
}
for (const [field, envVar] of Object.entries(OPTIONAL_FIELD_ENV)) {
    content = setField(content, field, process.env[envVar] || "");
}

fs.writeFileSync(filePath, content);
console.log("firebase-init.js populated from environment variables.");
