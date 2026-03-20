import React from 'react';
import { Folder, MousePointerClick, Download, Circle, CheckCircle, Navigation, Home, ChevronRight, HelpCircle, Eye, ArrowDownToLine, ChevronDown } from 'lucide-react';

const steps = [
    {
        icon: <Eye size={24} className="text-blue-400" />,
        title: "What is this?",
        description: "A private photo and video archive. Only people with an invite can sign in and view the media stored here."
    },
    {
        icon: <Folder size={24} className="text-blue-400" />,
        title: "Browse folders",
        description: "Tap any folder to open it. Use the breadcrumb trail at the top to go back. If you have access to multiple buckets, use the dropdown in the header to switch between them."
    },
    {
        icon: <MousePointerClick size={24} className="text-blue-400" />,
        title: "Preview photos & videos",
        description: "Tap any thumbnail to open a full-size preview. Videos will play automatically. Tap outside the preview or press the X to close it."
    },
    {
        icon: <ArrowDownToLine size={24} className="text-blue-400" />,
        title: "Download files",
        items: [
            { icon: <Circle size={14} className="text-neutral-400 inline" />, text: "Tap the circle icon on a thumbnail to select it" },
            { icon: <CheckCircle size={14} className="text-blue-400 inline" />, text: "Selected items show a blue checkmark" },
            { icon: <Download size={14} className="text-blue-400 inline" />, text: "Hit the Download button in the header to save your selection" },
        ],
        description: "Select one file for a direct download, or select multiple for a zip file."
    },
    {
        icon: <Navigation size={24} className="text-blue-400" />,
        title: "Navigation tips",
        items: [
            { icon: <Home size={14} className="text-neutral-400 inline" />, text: "Breadcrumbs let you jump back to any parent folder" },
            { icon: <ChevronDown size={14} className="text-neutral-400 inline" />, text: "Bucket dropdown (header) switches between storage locations" },
            { icon: <HelpCircle size={14} className="text-neutral-400 inline" />, text: "Tap the help icon in the gallery header to see these instructions again" },
        ]
    },
];

export default function LandingPage({ loginButton, onClose }) {
    return (
        <div className="min-h-screen bg-neutral-900 text-white flex flex-col items-center justify-center px-4 py-12">
            <div className="w-full max-w-xl">
                {/* Header */}
                <div className="text-center mb-10 relative">
                    {onClose && (
                        <button
                            onClick={onClose}
                            className="absolute -top-2 right-0 text-neutral-400 hover:text-white transition-colors"
                            aria-label="Close help"
                        >
                            <span className="text-2xl font-light">&times;</span>
                        </button>
                    )}
                    <h1 className="text-3xl font-bold tracking-tight mb-2">
                        <span className="text-blue-500">GCP</span> Bucket Viewer
                    </h1>
                    <p className="text-neutral-400">Your private media archive</p>
                </div>

                {/* Steps */}
                <div className="space-y-4">
                    {steps.map((step, i) => (
                        <div key={i} className="bg-neutral-800 border border-neutral-700 rounded-xl p-5">
                            <div className="flex items-center gap-3 mb-2">
                                {step.icon}
                                <h2 className="text-base font-semibold">{step.title}</h2>
                            </div>
                            {step.description && (
                                <p className="text-sm text-neutral-400 leading-relaxed ml-9">{step.description}</p>
                            )}
                            {step.items && (
                                <ul className="mt-2 space-y-2 ml-9">
                                    {step.items.map((item, j) => (
                                        <li key={j} className="flex items-center gap-2 text-sm text-neutral-400">
                                            {item.icon}
                                            <span>{item.text}</span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    ))}
                </div>

                {/* Login button slot */}
                {loginButton && (
                    <div className="mt-10 flex justify-center">
                        {loginButton}
                    </div>
                )}
            </div>
        </div>
    );
}
