import {useEffect, useState} from 'react';
import {auth, firebaseEnabled, startSession} from './firebase';
import {setAccount} from './api';
import App from './App';

// Visitors open the demo directly. An anonymous identity separates each browser's
// records without requiring registration or a sign-in screen.
export default function Session() {
  const [ready, setReady] = useState(!firebaseEnabled);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    startSession().then(() => {
      if (!active) return;
      setAccount(auth?.currentUser || null);
      setReady(true);
    }).catch(() => {if (active) setError('We could not open your session. Please try again.');});
    return () => {active = false;};
  }, []);
  if (ready) return <App />;
  return <main className="session-loading" aria-busy={!error}>
    {error ? <div role="alert"><p>{error}</p><button className="primary" onClick={() => location.reload()}>Try again</button></div> : 'Opening Re.View…'}
  </main>;
}
