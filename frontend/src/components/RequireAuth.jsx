import { Navigate, useLocation } from 'react-router-dom';
import useStore from '../store/useStore';

const RequireAuth = ({ children }) => {
  const { user } = useStore();
  const location = useLocation();
  return user ? children : <Navigate to="/" replace state={{ from: location.pathname }} />;
};

export default RequireAuth;
