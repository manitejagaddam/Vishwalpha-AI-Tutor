import React, { useState, useEffect } from 'react';
import { adminApi } from '../api/admin';
import { Upload, FileText, CheckCircle, AlertCircle, Clock, RefreshCw } from 'lucide-react';

const AdminPage = () => {
  const [adminKey, setAdminKey] = useState(localStorage.getItem('vishwalpha_admin_key') || '');
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  // Form state
  const [file, setFile] = useState(null);
  const [formData, setFormData] = useState({
    board_name: 'NCERT',
    class_num: 10,
    subject_name: 'Science',
    book_title: 'NCERT Science Class 10',
    book_natural_key: 'NCERT_10_Science_en',
    chapter_title: 'Chemical Reactions',
    chapter_number: 1,
  });

  const handleKeyChange = (e) => {
    const val = e.target.value;
    setAdminKey(val);
    localStorage.setItem('vishwalpha_admin_key', val);
  };

  const loadLogs = async () => {
    if (!adminKey) return;
    try {
      const data = await adminApi.getIngestionLogs(adminKey);
      setLogs(data);
    } catch (err) {
      console.error(err);
      if (err.response?.status === 401 || err.response?.status === 403) {
        setError('Invalid Admin Key');
      }
    }
  };

  useEffect(() => {
    loadLogs();
  }, [adminKey]);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) {
      setError('Please select a PDF file first.');
      return;
    }
    if (!adminKey) {
      setError('Please enter the Admin Key.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const uploadData = new FormData();
      uploadData.append('file', file);
      uploadData.append('board_name', formData.board_name);
      uploadData.append('class_num', formData.class_num);
      uploadData.append('subject_name', formData.subject_name);
      uploadData.append('book_title', formData.book_title);
      uploadData.append('book_natural_key', formData.book_natural_key);
      uploadData.append('chapter_title', formData.chapter_title);
      uploadData.append('chapter_number', formData.chapter_number);

      await adminApi.ingestPdf(adminKey, uploadData);
      
      // Refresh logs
      await loadLogs();
      setFile(null);
      alert('Ingestion completed successfully!');
      
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.detail || err.message || 'Ingestion failed');
    } finally {
      setLoading(false);
    }
  };

  const StatusBadge = ({ status }) => {
    const map = {
      complete: { icon: CheckCircle, color: 'text-green-500', bg: 'bg-green-100' },
      partial: { icon: AlertCircle, color: 'text-yellow-500', bg: 'bg-yellow-100' },
      needs_review: { icon: AlertCircle, color: 'text-orange-500', bg: 'bg-orange-100' },
      failed: { icon: AlertCircle, color: 'text-red-500', bg: 'bg-red-100' },
      in_progress: { icon: Clock, color: 'text-blue-500', bg: 'bg-blue-100' }
    };
    
    const conf = map[status] || map.failed;
    const Icon = conf.icon;
    
    return (
      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${conf.bg} ${conf.color}`}>
        <Icon className="w-4 h-4 mr-1" />
        {status}
      </span>
    );
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center py-10 px-4">
      <div className="max-w-6xl w-full grid grid-cols-1 md:grid-cols-2 gap-8">
        
        {/* Left Col: Upload Form */}
        <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100">
          <div className="flex items-center space-x-2 mb-6">
            <Upload className="w-6 h-6 text-indigo-600" />
            <h2 className="text-2xl font-bold text-gray-800">Admin Ingestion</h2>
          </div>

          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-1">Admin API Key</label>
            <input 
              type="password" 
              value={adminKey}
              onChange={handleKeyChange}
              className="w-full p-2 border border-gray-300 rounded focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              placeholder="Enter Admin API Key"
            />
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">PDF File</label>
              <input 
                type="file" 
                accept=".pdf"
                onChange={handleFileChange}
                className="w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Board</label>
                <input type="text" name="board_name" value={formData.board_name} onChange={handleInputChange} className="w-full p-2 border rounded" required />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Class Level</label>
                <input type="number" name="class_num" value={formData.class_num} onChange={handleInputChange} className="w-full p-2 border rounded" required />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Subject</label>
                <input type="text" name="subject_name" value={formData.subject_name} onChange={handleInputChange} className="w-full p-2 border rounded" required />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Chapter Number</label>
                <input type="number" name="chapter_number" value={formData.chapter_number} onChange={handleInputChange} className="w-full p-2 border rounded" required />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Book Title</label>
              <input type="text" name="book_title" value={formData.book_title} onChange={handleInputChange} className="w-full p-2 border rounded" required />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Book Key (Unique)</label>
              <input type="text" name="book_natural_key" value={formData.book_natural_key} onChange={handleInputChange} className="w-full p-2 border rounded" required />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Chapter Title</label>
              <input type="text" name="chapter_title" value={formData.chapter_title} onChange={handleInputChange} className="w-full p-2 border rounded" required />
            </div>

            <button 
              type="submit" 
              disabled={loading}
              className={`w-full py-3 rounded text-white font-medium flex justify-center items-center ${loading ? 'bg-indigo-400 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-700'}`}
            >
              {loading ? (
                <>
                  <RefreshCw className="w-5 h-5 mr-2 animate-spin" />
                  Processing... (May take several minutes)
                </>
              ) : (
                'Upload & Ingest PDF'
              )}
            </button>
          </form>
        </div>

        {/* Right Col: Logs */}
        <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 flex flex-col">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center space-x-2">
              <FileText className="w-6 h-6 text-gray-600" />
              <h2 className="text-2xl font-bold text-gray-800">Recent Ingestions</h2>
            </div>
            <button onClick={loadLogs} className="p-2 text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-full">
              <RefreshCw className="w-5 h-5" />
            </button>
          </div>

          <div className="overflow-y-auto flex-1 max-h-[700px] pr-2 space-y-4">
            {logs.length === 0 ? (
              <div className="text-center text-gray-500 py-10">No ingestion logs found.</div>
            ) : (
              logs.map((log) => (
                <div key={log.id} className="p-4 border border-gray-200 rounded-lg hover:border-indigo-300 transition-colors">
                  <div className="flex justify-between items-start mb-2">
                    <div>
                      <h3 className="font-semibold text-gray-900">{log.book_natural_key || `Book ID: ${log.book_id}`}</h3>
                      <p className="text-sm text-gray-500">Chapter {log.chapter_number}</p>
                    </div>
                    <StatusBadge status={log.status} />
                  </div>
                  
                  <div className="grid grid-cols-2 gap-2 mt-4 text-sm">
                    <div>
                      <span className="text-gray-500 block">Confidence</span>
                      <span className="font-medium text-gray-800">
                        {log.ingestion_confidence !== null ? `${(log.ingestion_confidence * 100).toFixed(1)}%` : 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-500 block">Date</span>
                      <span className="font-medium text-gray-800">
                        {new Date(log.ingested_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>

                  {log.error && (
                    <div className="mt-3 p-2 bg-red-50 text-red-700 text-xs rounded break-words">
                      {log.error}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminPage;
