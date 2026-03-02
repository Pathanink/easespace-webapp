importScripts('https://www.gstatic.com/firebasejs/9.0.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.0.0/firebase-messaging-compat.js');

const firebaseConfig = {
    apiKey: "{{ fb_config.apiKey }}",
    authDomain: "{{ fb_config.authDomain }}",
    projectId: "{{ fb_config.projectId }}",
    storageBucket: "{{ fb_config.storageBucket }}",
    messagingSenderId: "{{ fb_config.messagingSenderId }}",
    appId: "{{ fb_config.appId }}",
    measurementId: "{{ fb_config.measurementId }}"
};

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();