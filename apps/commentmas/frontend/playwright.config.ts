import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',timeout:30000,use:{baseURL:'http://127.0.0.1:5173',channel:'chrome',headless:true},webServer:{command:'npm run dev',url:'http://127.0.0.1:5173',reuseExistingServer:true},reporter:'list'});
