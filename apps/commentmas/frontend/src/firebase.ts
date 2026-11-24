import {initializeApp} from 'firebase/app';
import {getAuth, signInAnonymously} from 'firebase/auth';

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const firebaseEnabled = Boolean(config.apiKey && config.projectId && config.appId && config.authDomain);
export const auth = firebaseEnabled ? getAuth(initializeApp(config)) : null;
let starting: Promise<void> | null = null;
export function startSession() {
  if (!auth) return Promise.resolve();
  const instance = auth;
  if (!starting) starting = instance.authStateReady().then(async () => {
    if (!instance.currentUser) await signInAnonymously(instance);
  }).catch(error => {starting = null; throw error;});
  return starting;
}
