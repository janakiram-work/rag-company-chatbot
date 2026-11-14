import React from 'react';
import { AlertCircle, RotateCcw } from 'lucide-react';

export class TabErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error(`Error in tab [${this.props.tabTitle || 'Admin Tab'}]:`, error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
    if (this.props.onRetry) {
      try {
        this.props.onRetry();
      } catch (err) {
        console.error('Retry failed:', err);
      }
    }
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-6 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-xl my-4 text-center">
          <div className="flex flex-col items-center justify-center gap-3">
            <AlertCircle className="w-8 h-8 text-red-500" />
            <div>
              <h4 className="text-sm font-semibold text-red-800 dark:text-red-300">
                Failed to load {this.props.tabTitle || 'tab'}
              </h4>
              <p className="text-xs text-red-600 dark:text-red-400 mt-1 max-w-md">
                {this.state.error?.message || 'An unexpected error occurred while rendering this tab.'}
              </p>
            </div>
            <button
              type="button"
              onClick={this.handleRetry}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-xs transition"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Retry
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default TabErrorBoundary;
