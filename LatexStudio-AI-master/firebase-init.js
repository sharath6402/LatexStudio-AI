import { initializeApp } from "https://www.gstatic.com/firebasejs/11.9.1/firebase-app.js";

import {
    getAuth,
    onAuthStateChanged,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signInWithPopup,
    GoogleAuthProvider,
    signOut,
    updateProfile
} from "https://www.gstatic.com/firebasejs/11.9.1/firebase-auth.js";

import {
    getFirestore,
    collection,
    collectionGroup,
    query,
    where,
    orderBy,
    doc,
    getDoc,
    getDocs,
    addDoc,
    setDoc,
    deleteDoc,
    serverTimestamp
} from "https://www.gstatic.com/firebasejs/11.9.1/firebase-firestore.js";

import {
    getStorage,
    ref,
    uploadBytes,
    getDownloadURL,
    deleteObject
} from "https://www.gstatic.com/firebasejs/11.9.1/firebase-storage.js";

// Fill in with your own Firebase project's config (Firebase Console -> Project
// Settings -> General -> Your apps -> SDK setup and configuration).
const firebaseConfig = {
    apiKey: "AIzaSyDQXFp0A-QdpbGilcJnuiUw3Jmoy6nQ1sA",
    authDomain: "latexeditorai.firebaseapp.com",
    projectId: "latexeditorai",
    storageBucket: "latexeditorai.firebasestorage.app",
    messagingSenderId: "1011525388536",
    appId: "1:1011525388536:web:10b375a26bc106d41f930d",
    measurementId: "G-BW3YTHN9JP"
};

const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const db = getFirestore(app);
export const storage = getStorage(app);
export const googleProvider = new GoogleAuthProvider();

export {
    onAuthStateChanged,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signInWithPopup,
    GoogleAuthProvider,
    signOut,
    updateProfile,
    collection,
    collectionGroup,
    query,
    where,
    orderBy,
    doc,
    getDoc,
    getDocs,
    addDoc,
    setDoc,
    deleteDoc,
    serverTimestamp,
    ref,
    uploadBytes,
    getDownloadURL,
    deleteObject
};

// Redirects to login.html if no user is signed in. Resolves with the user otherwise.
export function requireAuth() {
    return new Promise((resolve) => {
        onAuthStateChanged(auth, (user) => {
            if (!user) {
                window.location.href = "/login";
            } else {
                resolve(user);
            }
        });
    });
}
