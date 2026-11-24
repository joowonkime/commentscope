import React from 'react';
import {createRoot} from 'react-dom/client';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/geologica/700.css';
import Session from './Session';
import './styles.css';

createRoot(document.getElementById('root')!).render(<React.StrictMode><Session/></React.StrictMode>);
