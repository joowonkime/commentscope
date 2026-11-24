import {useEffect, useState} from 'react';
import {auth, firebaseEnabled, startSession} from './firebase';
import {setAccount} from './api';
import App from './App';
import VideoStart from './VideoStart';

// The video chooser and each workspace use the same anonymous browser identity.
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
  if (ready) {
    const query = new URLSearchParams(location.search);
    const savedLink = ['#explore', '#converse', '#reflect', '#start'].includes(location.hash);
    return query.get('video') || (savedLink && !query.has('prepare')) ? <App /> : <VideoStart />;
  }
  return <main className="session-loading" aria-busy={!error}>
    {error ? <div role="alert"><p>{error}</p><button className="primary" onClick={() => location.reload()}>Try again</button></div> : 'Opening Re.View…'}
  </main>;
}
