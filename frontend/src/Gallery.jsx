import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { useAuth } from './AuthContext';
import { Download, CheckCircle, Circle, Play, Image as ImageIcon, LogOut, ChevronDown, X, Folder, Home, FileArchive, File, ChevronRight, HelpCircle } from 'lucide-react';
import LandingPage from './LandingPage';
import { clsx } from 'clsx';

export default function Gallery() {
    const { apiBase, logout, buckets, bucketPermissions, currentBucket, setCurrentBucket, user, bucketsLoading } = useAuth();
    const [items, setItems] = useState([]);
    const [pageToken, setPageToken] = useState(null);
    const [loading, setLoading] = useState(false);
    const [selected, setSelected] = useState(new Set());
    const [previewItem, setPreviewItem] = useState(null);
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const [downloading, setDownloading] = useState(false);
    const [currentPrefix, setCurrentPrefix] = useState('');
    const [subdirectories, setSubdirectories] = useState([]);
    const [showHelp, setShowHelp] = useState(false);

    // Get prefix restrictions for the current bucket
    const currentBucketPerms = bucketPermissions.find(b => b.name === currentBucket);
    const allowedPrefixes = currentBucketPerms?.prefixes || [];
    const hasRestrictions = allowedPrefixes.length > 0;

    // The minimum prefix level the user can navigate to
    const basePrefix = hasRestrictions && allowedPrefixes.length === 1 ? allowedPrefixes[0] : '';

    // Auto-navigate into the single allowed prefix on bucket change
    useEffect(() => {
        if (hasRestrictions && allowedPrefixes.length === 1) {
            setCurrentPrefix(allowedPrefixes[0]);
        } else {
            setCurrentPrefix('');
        }
    }, [currentBucket]);

    const loader = useRef(null);
    const loadingRef = useRef(false);
    const pageTokenRef = useRef(null);

    const fetchItems = useCallback(async (token, signal) => {
        if (loadingRef.current || !currentBucket) return;
        // Multi-prefix restricted user at root: don't fetch, show prefix folders instead
        if (hasRestrictions && allowedPrefixes.length > 1 && !currentPrefix) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const res = await axios.get(`${apiBase}/api/media`, {
                params: {
                    bucket_name: currentBucket,
                    page_token: token,
                    limit: 50,
                    start_date: startDate || undefined,
                    end_date: endDate || undefined,
                    prefix: currentPrefix || undefined
                },
                signal: signal // Use the abort signal
            });

            if (res.data.subdirectories) {
                setSubdirectories(res.data.subdirectories);
            }

            setItems(prev => token ? [...prev, ...res.data.items] : res.data.items);
            const nextToken = res.data.nextPageToken;
            setPageToken(nextToken);
            pageTokenRef.current = nextToken;
        } catch (err) {
            if (axios.isCancel(err)) {
                // Avoid logging if explicitly cancelled
                return;
            }
            console.error("Fetch failed", err);
        } finally {
            loadingRef.current = false;
            setLoading(false);
        }
    }, [apiBase, currentBucket, startDate, endDate, currentPrefix]);

    // Reset logic when bucket changes
    useEffect(() => {
        const controller = new AbortController();
        setItems([]);
        setPageToken(null);
        pageTokenRef.current = null;
        setSelected(new Set());
        fetchItems(null, controller.signal);

        return () => controller.abort();
    }, [currentBucket, startDate, endDate, currentPrefix]);

    // Infinite scroll — uses pageTokenRef to avoid re-creating the effect on every pageToken change
    useEffect(() => {
        const observer = new IntersectionObserver(entries => {
            if (entries[0].isIntersecting && pageTokenRef.current && !loadingRef.current) {
                fetchItems(pageTokenRef.current);
            }
        });
        if (loader.current) observer.observe(loader.current);
        return () => observer.disconnect();
    }, [fetchItems]);

    const toggleSelect = (name) => {
        setSelected(prev => {
            const newSet = new Set(prev);
            if (newSet.has(name)) newSet.delete(name);
            else newSet.add(name);
            return newSet;
        });
    };

    const handleDownloadBatch = async () => {
        if (selected.size === 0 || downloading) return;
        setDownloading(true);

        const selectedList = Array.from(selected);

        // Optimization: If only one file is selected, use the direct stream URL
        // This lets the browser handle the download and uses the correct original filename
        if (selectedList.length === 1) {
            const fileName = selectedList[0];
            const token = user?.token;
            const url = `${apiBase}/api/stream/${encodeURIComponent(fileName)}?bucket_name=${currentBucket}&token=${token}`;

            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', fileName.split('/').pop());
            document.body.appendChild(link);
            link.click();
            link.remove();
            return;
        }

        try {
            const response = await axios.post(`${apiBase}/api/download-batch`,
                selectedList,
                {
                    params: { bucket_name: currentBucket },
                    responseType: 'blob'
                }
            );

            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;

            // Try to get filename from content-disposition header if available
            let fileName = `media_batch_${new Date().toISOString().split('T')[0]}.zip`;
            const contentDisposition = response.headers['content-disposition'];
            if (contentDisposition) {
                const fileNameMatch = contentDisposition.match(/filename="?(.+)"?/);
                if (fileNameMatch && fileNameMatch.length > 1) {
                    fileName = fileNameMatch[1];
                }
            }

            link.setAttribute('download', fileName);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            console.error("Download failed", err);
            alert("Download failed. See console.");
        } finally {
            setDownloading(false);
        }
    };

const Breadcrumbs = () => {
        const parts = currentPrefix.split('/').filter(Boolean);
        const baseParts = basePrefix.split('/').filter(Boolean);
        // Only show breadcrumb parts at or below the base prefix level
        const visibleParts = hasRestrictions ? parts.slice(baseParts.length) : parts;
        const canNavigateToRoot = !hasRestrictions;

        return (
            <div className="flex items-center gap-1 text-sm text-neutral-400 mb-6 bg-neutral-800/50 p-2 px-4 rounded-xl border border-neutral-700/50 w-fit">
                <button
                    onClick={() => setCurrentPrefix(basePrefix)}
                    className={clsx(
                        "flex items-center gap-2 transition-all",
                        canNavigateToRoot || currentPrefix !== basePrefix ? "hover:text-blue-500 hover:scale-105" : ""
                    )}
                >
                    <Home size={14} className={clsx(currentPrefix === basePrefix && "text-blue-500")} />
                    <span className={clsx(currentPrefix === basePrefix && "text-white font-semibold")}>
                        {hasRestrictions ? baseParts[baseParts.length - 1] || 'Root' : 'Root'}
                    </span>
                </button>
                {visibleParts.map((part, idx) => {
                    const path = [...baseParts, ...visibleParts.slice(0, idx + 1)].join('/') + '/';
                    const isLast = idx === visibleParts.length - 1;
                    return (
                        <React.Fragment key={path}>
                            <ChevronRight size={14} className="text-neutral-600 mx-1" />
                            <button
                                onClick={() => setCurrentPrefix(path)}
                                className={clsx(
                                    "transition-all hover:scale-105",
                                    isLast ? "text-white font-semibold cursor-default pointer-events-none" : "hover:text-blue-500"
                                )}
                            >
                                {part}
                            </button>
                        </React.Fragment>
                    );
                })}
            </div>
        );
    };

    if (bucketsLoading) {
        return (
            <div className="min-h-screen bg-neutral-900 text-white flex items-center justify-center">
                <div className="text-center">
                    <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mx-auto mb-4"></div>
                    <p className="text-neutral-400">Loading your buckets...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-neutral-900 text-white font-sans">
            {/* Header */}
            <header className="sticky top-0 z-10 bg-neutral-900/90 backdrop-blur-md border-b border-neutral-800 px-6 py-4 flex justify-between items-center">
                <div className="flex items-center">
                    <button
                        onClick={() => setCurrentPrefix('')}
                        className="text-xl font-bold tracking-tight hidden sm:block hover:opacity-80 transition-opacity"
                    >
                        <span className="text-blue-500 mr-2">GCP</span>Viewer
                    </button>

                    {/* Bucket Selector */}
                    <div className="relative ml-6 group">
                        <select
                            value={currentBucket || ''}
                            onChange={(e) => { setCurrentPrefix(''); setCurrentBucket(e.target.value); }}
                            className="bg-neutral-800 text-white border border-neutral-700 rounded-lg py-1 px-3 pr-8 appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            {buckets.map(b => <option key={b} value={b}>{b}</option>)}
                        </select>
                        <ChevronDown className="absolute right-2 top-2 pointer-events-none text-neutral-400" size={14} />
                    </div>

                    {/* Current Path Indicator */}
                    <div className="hidden lg:flex items-center gap-2 ml-4 border-l border-neutral-700 pl-4 text-xs font-mono text-neutral-500 lowercase">
                        <Folder size={12} />
                        <span className="truncate max-w-[200px]">{currentPrefix || 'root'}</span>
                    </div>

                    {/* Date Filters */}
                    <div className="flex items-center gap-2 ml-4 border-l border-neutral-700 pl-4 hidden md:flex">
                        <span className="text-xs font-semibold text-neutral-500 uppercase tracking-wider">Filter:</span>
                        <div className="flex items-center bg-neutral-800 border border-neutral-700 rounded-lg px-2 py-1 gap-2">
                            <input
                                type="date"
                                value={startDate}
                                onChange={(e) => setStartDate(e.target.value)}
                                className="bg-transparent text-xs text-white focus:outline-none"
                            />
                            <span className="text-neutral-600">to</span>
                            <input
                                type="date"
                                value={endDate}
                                onChange={(e) => setEndDate(e.target.value)}
                                className="bg-transparent text-xs text-white focus:outline-none"
                            />
                            {(startDate || endDate) && (
                                <button
                                    onClick={() => {
                                        setStartDate('');
                                        setEndDate('');
                                    }}
                                    className="text-neutral-500 hover:text-white"
                                >
                                    <X size={14} />
                                </button>
                            )}
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                    {selected.size > 0 && (
                        <button
                            onClick={handleDownloadBatch}
                            disabled={downloading}
                            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-full text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {downloading ? (
                                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                            ) : (
                                <Download size={16} />
                            )}
                            {downloading ? 'Processing...' : `Download (${selected.size})`}
                        </button>
                    )}
<button onClick={() => setShowHelp(true)} className="text-neutral-400 hover:text-white transition-colors" title="Help">
                        <HelpCircle size={20} />
                    </button>
                    <button onClick={logout} className="text-neutral-400 hover:text-white transition-colors">
                        <LogOut size={20} />
                    </button>
                </div>
            </header>

            {/* Grid */}
            <main className="p-4 sm:p-6">
                <Breadcrumbs />

                {/* Allowed Prefixes as Virtual Folders (for multi-prefix restricted users at root) */}
                {hasRestrictions && allowedPrefixes.length > 1 && currentPrefix === '' && (
                    <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4 mb-8">
                        {allowedPrefixes.map(p => (
                            <button
                                key={p}
                                onClick={() => setCurrentPrefix(p)}
                                className="flex items-center gap-3 bg-neutral-800 hover:bg-neutral-700 p-3 rounded-xl border border-neutral-700 transition-all hover:scale-[1.02] shadow-sm group"
                            >
                                <div className="p-2 bg-blue-500/10 rounded-lg group-hover:bg-blue-500/20 transition-colors">
                                    <Folder className="text-blue-500" size={20} fill="currentColor" fillOpacity={0.2} />
                                </div>
                                <span className="text-sm font-medium truncate">{p.split('/').filter(Boolean).pop()}</span>
                            </button>
                        ))}
                    </div>
                )}

                {/* Subdirectories Grid */}
                {subdirectories.length > 0 && (
                    <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4 mb-8">
                        {subdirectories.map(s => (
                            <button
                                key={s}
                                onClick={() => setCurrentPrefix(s)}
                                className="flex items-center gap-3 bg-neutral-800 hover:bg-neutral-700 p-3 rounded-xl border border-neutral-700 transition-all hover:scale-[1.02] shadow-sm group"
                            >
                                <div className="p-2 bg-blue-500/10 rounded-lg group-hover:bg-blue-500/20 transition-colors">
                                    <Folder className="text-blue-500" size={20} fill="currentColor" fillOpacity={0.2} />
                                </div>
                                <span className="text-sm font-medium truncate">{s.split('/').filter(Boolean).pop()}</span>
                            </button>
                        ))}
                    </div>
                )}
                <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10 gap-2">
                    {items.map((item) => (
                        <div
                            key={item.name}
                            className={clsx(
                                "group relative aspect-square bg-neutral-800 rounded-lg overflow-hidden border transition-all cursor-pointer",
                                selected.has(item.name) ? "border-blue-500 ring-2 ring-blue-500/50" : "border-neutral-800 hover:border-neutral-600"
                            )}
                            onClick={() => setPreviewItem(item)}
                        >
                            {(item.is_image || item.is_video) ? (
                                <Thumbnail item={item} apiBase={apiBase} bucket={currentBucket} />
                            ) : (
                                <div className="w-full h-full bg-neutral-800 flex flex-col items-center justify-center gap-2 p-4">
                                    {item.name.toLowerCase().endsWith('.zip') ? (
                                        <FileArchive size={32} className="text-neutral-500" />
                                    ) : (
                                        <File size={32} className="text-neutral-500" />
                                    )}
                                    <span className="text-[10px] text-neutral-500 text-center truncate w-full">
                                        {item.name.split('.').pop()?.toUpperCase() || 'FILE'}
                                    </span>
                                </div>
                            )}

                            {/* Selection Overlay */}
                            <div
                                className="absolute top-2 right-2 p-1 rounded-full text-white mix-blend-difference z-20 hover:scale-110 transition-transform"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    toggleSelect(item.name);
                                }}
                            >
                                {selected.has(item.name)
                                    ? <CheckCircle className="fill-blue-500 text-white" size={24} />
                                    : <Circle className="text-white/70 hover:text-white" size={24} />
                                }
                            </div>

                            {/* Metadata Overlay */}
                            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-3 pt-8 opacity-0 group-hover:opacity-100 transition-opacity">
                                <p className="text-xs truncate font-medium">{item.name.split('/').pop()}</p>
                                <p className="text-[10px] text-neutral-400">{(item.size / 1024 / 1024).toFixed(1)} MB</p>
                            </div>

                            {item.is_video && (
                                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                                    <div className="bg-black/30 w-10 h-10 rounded-full flex items-center justify-center backdrop-blur-sm">
                                        <Play size={20} className="fill-white text-white ml-1" />
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                </div>

                {/* Loader */}
                <div ref={loader} className="py-8 flex justify-center text-neutral-500">
                    {loading ? "Loading..." : pageToken ? "Load More" : "End of list"}
                </div>
            </main>

            {/* Preview Modal */}
            {previewItem && (
                <PreviewModal
                    item={previewItem}
                    onClose={() => setPreviewItem(null)}
                    apiBase={apiBase}
                    bucket={currentBucket}
                />
            )}

            {/* Help Overlay */}
            {showHelp && (
                <div className="fixed inset-0 z-50 bg-neutral-900/95 backdrop-blur-sm overflow-y-auto">
                    <LandingPage onClose={() => setShowHelp(false)} />
                </div>
            )}
        </div>
    );
}

const PreviewModal = ({ item, onClose, apiBase, bucket }) => {
    const { user } = useAuth();
    const [mediaUrl, setMediaUrl] = useState(null);
    const [loading, setLoading] = useState(true);

    const videoRef = useRef(null);

    useEffect(() => {
        const token = user?.token;
        setMediaUrl(`${apiBase}/api/stream/${encodeURIComponent(item.name)}?bucket_name=${bucket}&token=${token}`);
        setLoading(false);

        return () => {
            // Explicitly stop video and clear memory
            if (videoRef.current) {
                videoRef.current.pause();
                videoRef.current.src = "";
                videoRef.current.load();
            }
        };
    }, [item, apiBase, bucket, user]);

    if (!item) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/95 backdrop-blur-sm p-4" onClick={onClose}>
            <button
                onClick={onClose}
                className="absolute top-6 right-6 text-white hover:text-blue-500 z-50 transition-colors"
            >
                <X size={32} />
            </button>

            <div className="relative w-full h-full flex items-center justify-center" onClick={e => e.stopPropagation()}>
                {loading && (
                    <div className="flex flex-col items-center gap-4 text-white">
                        <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin"></div>
                        <p className="text-sm font-medium animate-pulse">Loading high-res...</p>
                    </div>
                )}

                {mediaUrl && (
                    item.is_video ? (
                        <video
                            ref={videoRef}
                            src={mediaUrl}
                            controls
                            autoPlay
                            className="max-w-full max-h-full rounded-lg shadow-2xl"
                        />
                    ) : (
                        <img
                            src={mediaUrl}
                            alt={item.name}
                            className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
                        />
                    )
                )}

                <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-neutral-900/80 backdrop-blur-md px-4 py-2 rounded-full border border-neutral-700 flex items-center gap-4">
                    <p className="text-sm font-medium text-white truncate max-w-[200px]">{item.name.split('/').pop()}</p>
                    <a
                        href={`${apiBase}/api/stream/${encodeURIComponent(item.name)}?bucket_name=${bucket}&token=${user?.token}`}
                        download={item.name.split('/').pop()}
                        className="text-neutral-400 hover:text-white transition-colors flex items-center gap-2"
                    >
                        <Download size={18} />
                        <span className="text-xs">Download</span>
                    </a>
                </div>
            </div>
        </div>
    );
};

const Thumbnail = ({ item, apiBase, bucket }) => {
    const [imageSrc, setImageSrc] = useState(null);
    const [isGenerating, setIsGenerating] = useState(true);
    const [error, setError] = useState(false);

    useEffect(() => {
        let active = true;
        let retryCount = 0;
        const maxRetries = 10;
        const controller = new AbortController();

        const fetchThumbnail = async () => {
            if (!active) return;

            try {
                const res = await axios.get(`${apiBase}/api/thumbnail/${item.name}`, {
                    params: { bucket_name: bucket },
                    responseType: 'blob',
                    signal: controller.signal
                });

                if (active) {
                    const url = URL.createObjectURL(res.data);
                    setImageSrc(url);
                    setIsGenerating(false);
                }
            } catch (err) {
                if (axios.isCancel(err)) return;

                if (err.response && err.response.status === 202 && retryCount < maxRetries) {
                    if (active) setIsGenerating(true);
                    retryCount++;
                    setTimeout(fetchThumbnail, 2000);
                } else {
                    console.error("Thumb error", err);
                    if (active) {
                        setIsGenerating(false);
                        setError(true);
                    }
                }
            }
        };

        fetchThumbnail();

        return () => {
            active = false;
            controller.abort();
            if (imageSrc) URL.revokeObjectURL(imageSrc);
        };
    }, [apiBase, bucket, item.name]); // imageSrc removed from deps to avoid loop

    if (error) {
        return (
            <div className="w-full h-full bg-neutral-800 flex items-center justify-center text-neutral-600">
                <ImageIcon size={24} />
            </div>
        );
    }

    return (
        <div className="w-full h-full bg-neutral-800 flex items-center justify-center">
            {imageSrc ? (
                <img
                    src={imageSrc}
                    alt={item.name}
                    className="w-full h-full object-cover"
                />
            ) : (
                <div className="w-8 h-8 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin"></div>
            )}
        </div>
    )
}
