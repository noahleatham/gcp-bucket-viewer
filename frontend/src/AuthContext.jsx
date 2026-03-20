import React, { createContext, useContext, useState, useEffect } from 'react';
import { GoogleOAuthProvider, GoogleLogin } from '@react-oauth/google';
import axios from 'axios';
import LandingPage from './LandingPage';

const AuthContext = createContext(null);

export const useAuth = () => useContext(AuthContext);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [token, setToken] = useState(localStorage.getItem('google_token'));
    const [config, setConfig] = useState(null);
    const [bucketPermissions, setBucketPermissions] = useState([]);
    const [currentBucket, setCurrentBucket] = useState(null);
    const [bucketsLoading, setBucketsLoading] = useState(false);

    const apiBase = import.meta.env.VITE_API_BASE || '';

    const login = (newToken) => {
        setToken(newToken);
        localStorage.setItem('google_token', newToken);
    };

    const logout = () => {
        setToken(null);
        setUser(null);
        setBucketPermissions([]);
        setCurrentBucket(null);
        localStorage.removeItem('google_token');
        delete axios.defaults.headers.common['Authorization'];
    };

    useEffect(() => {
        axios.get(`${apiBase}/api/config`)
            .then(res => {
                setConfig(res.data);
            })
            .catch(err => console.error("Failed to load config", err));
    }, []);

    // Fetch user-specific buckets after authentication
    useEffect(() => {
        if (!token) {
            setBucketPermissions([]);
            setCurrentBucket(null);
            return;
        }

        setBucketsLoading(true);
        axios.get(`${apiBase}/api/buckets`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(res => {
                const buckets = res.data.buckets || [];
                setBucketPermissions(buckets);
                if (buckets.length > 0) {
                    setCurrentBucket(buckets[0].name);
                }
            })
            .catch(err => {
                console.error("Failed to load buckets", err);
                if (err.response && err.response.status === 401) {
                    logout();
                }
            })
            .finally(() => setBucketsLoading(false));
    }, [token]);

    useEffect(() => {
        if (token) {
            setUser({ token });
            axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
        }

        // Add interceptor to handle expired tokens (401)
        const interceptor = axios.interceptors.response.use(
            response => response,
            error => {
                if (error.response && error.response.status === 401) {
                    console.log("Session expired, logging out...");
                    logout();
                }
                return Promise.reject(error);
            }
        );

        return () => axios.interceptors.response.eject(interceptor);
    }, [token]);

    if (!config) return <div className="p-10 text-center text-white">Loading configuration...</div>;

    return (
        <GoogleOAuthProvider clientId={config.google_client_id}>
            <AuthContext.Provider value={{
                user,
                login,
                logout,
                bucketPermissions,
                buckets: bucketPermissions.map(b => b.name),
                currentBucket,
                setCurrentBucket,
                bucketsLoading,
                apiBase,
            }}>
                {children}
            </AuthContext.Provider>
        </GoogleOAuthProvider>
    );
};

export const LoginButton = () => {
    const { login } = useAuth();
    return (
        <LandingPage
            loginButton={
                <GoogleLogin
                    onSuccess={credentialResponse => {
                        login(credentialResponse.credential);
                    }}
                    onError={() => {
                        console.log('Login Failed');
                    }}
                    theme="filled_black"
                    shape="pill"
                />
            }
        />
    );
};
