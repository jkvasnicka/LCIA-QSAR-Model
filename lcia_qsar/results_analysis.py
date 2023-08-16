'''
This module is responsible for analyzing
the results of machine learning models. It includes functionalities for
in-sample and out-of-sample predictions, feature importance analysis, and
other result-related tasks.

Classes
-------
ResultsAnalyzer 
    Analyzes the results of machine learning models and provides methods for 
    predictions, feature importance, and more.
'''

import pandas as pd 

import sys
sys.path.append('..')
from common.workflow_base import SupervisedLearningWorkflow

# TODO: The entire config may not be needed
#region: ResultsAnalyzer.__init__
class ResultsAnalyzer:
    '''
    A class to analyze the results of machine learning models.

    This class provides methods to obtain in-sample and out-of-sample 
    predictions, determine important features, and perform other 
    result-related analyses.

    Attributes
    ----------
    results_manager : A `ResultsManager` instance for managing results data.
    data_manager : A `DataManager` instance for managing data.
    config : UnifiedConfiguration object

    Methods
    -------
    get_in_sample_prediction(model_key, inverse_transform=False) 
        Get in-sample predictions.
    predict_out_of_sample(model_key, inverse_transform=False) 
        Predict out-of-sample data.
    get_prediction(model_key, X, inverse_transform=False) 
        Get predictions for given input.
    get_important_features(model_key) 
        Get important features for the model.
    get_important_features_replicates(model_key) 
        Get important features for each replicate.
    split_replicates(dataframe, stride) 
        Split a replicates DataFrame into individual DataFrames.
    '''
    def __init__(self, results_manager, data_manager, config):
        '''
        Initialize the ResultsAnalyzer class.

        Parameters
        ----------
        results_manager : A `ResultsManager` instance
        data_manager : A `DataManager` instance
        config : UnifiedConfiguration object
        '''
        self.results_manager = results_manager
        self.data_manager = data_manager
        self.config = config
#endregion

    #region: get_in_sample_prediction
    def get_in_sample_prediction(self, model_key, inverse_transform=False):
        '''
        Get in-sample predictions for the given model key.

        Parameters
        ----------
        model_key : Tuple
            Key identifying the model for which predictions are required.
        inverse_transform : bool, optional
            If True, applies the inverse transform to the predictions 
            (default is False).

        Returns
        -------
        y_pred : pandas.Series
            Predicted target values.
        X : pandas.DataFrame
            Features used for prediction.
        y_true : pandas.Series
            True target values.
        '''
        model_key_names = self.results_manager.read_model_key_names()
        key_for = dict(zip(model_key_names, model_key))
        # Load only the intersection of samples
        X, y_true = self.data_manager.load_features_and_target(**key_for)

        y_pred, X = self.get_prediction(model_key, X, inverse_transform)

        return y_pred, X, y_true
    #endregion

    #region: predict_out_of_sample
    def predict_out_of_sample(self, model_key, inverse_transform=False):
        '''
        Predict out-of-sample data for the given model key.

        Parameters
        ----------
        model_key : Tuple
            Key identifying the model for which predictions are required.
        inverse_transform : bool, optional
            If True, applies the inverse transform to the predictions 
            (default is False).

        Returns
        -------
        y_pred : pandas.Series
            Predicted target values.
        X : pandas.DataFrame
            Features used for prediction.
        '''
        model_key_names = self.results_manager.read_model_key_names()
        key_for = dict(zip(model_key_names, model_key))
        # Load the entire file
        X = self.data_manager.load_features(**key_for)

        y_pred, X = self.get_prediction(model_key, X, inverse_transform)

        return y_pred, X
    #endregion

    #region: get_prediction
    def get_prediction(self, model_key, X, inverse_transform=False):
        '''
        Get predictions for the given input.

        Parameters
        ----------
        model_key : Tuple
            Key identifying the model for which predictions are required.
        X : pandas.DataFrame
            Features used for prediction.
        inverse_transform : bool, optional
            If True, applies the inverse transform to the predictions 
            (default is False).

        Returns
        -------
        y_pred : pandas.Series
            Predicted target values.
        X : pandas.DataFrame
            Features used for prediction with fitted columns.
        '''
        estimator = self.results_manager.read_estimator(model_key)
        X = X[estimator.feature_names_in_]
        y_pred = pd.Series(estimator.predict(X), index=X.index)
        if inverse_transform:
            y_pred = 10**y_pred
        return y_pred, X
    #endregion

    #region: get_important_features
    def get_important_features(self, model_key):
        '''
        Get important features for the model identified by the given key.

        Parameters
        ----------
        model_key : Tuple
            Key identifying the model.

        Returns
        -------
        feature_names : list
            List of important feature names.
        '''
        result_df = self.results_manager.read_result(model_key, 'importances')

        # Get the parameters to reproduce the feature selection
        kwargs = self.config.model.kwargs_build_model
        args = (
            kwargs['criterion_metric'],
            kwargs['n_features']
        )
        
        feature_names = (
            SupervisedLearningWorkflow.select_features(result_df, *args)
        )
        return feature_names
    #endregion

    #region: get_important_features_replicates
    def get_important_features_replicates(self, model_key):
        '''
        Get important features for each replicate of the model identified by 
        the given key.

        Parameters
        ----------
        model_key : Tuple
            Key identifying the model.

        Returns
        -------
        feature_names_for_replicate : dict
            Dictionary mapping replicate index to the list of important 
            features.
        '''
        result_df = self.results_manager.read_result(
            model_key, 
            'importances_replicates'
            )

        # Get the parameters to reproduce the feature selection
        kwargs = self.config.model.kwargs_build_model
        stride = (
            kwargs['n_splits_select']
            * kwargs['n_repeats_select'] 
            * kwargs['n_repeats_perm']
        )
        args = (
            kwargs['criterion_metric'],
            kwargs['n_features']
        )

        list_of_df = ResultsAnalyzer.split_replicates(result_df, stride)

        feature_names_for_replicate = {
            i : SupervisedLearningWorkflow.select_features(result_df, *args) 
            for i, result_df in enumerate(list_of_df)
            }
        return feature_names_for_replicate
    #endregion

    #region: split_replicates
    @staticmethod
    def split_replicates(dataframe, stride):
        '''
        Split a replicates DataFrame into individual DataFrames.

        Parameters
        ----------
        dataframe : pandas.DataFrame
            DataFrame containing replicates data.
        stride : int
            Stride to use for splitting the DataFrame.

        Returns
        -------
        list_of_df : list
            List of DataFrames, each containing a subset of replicates.
        '''
        list_of_df = []
        length = len(dataframe)
        start = 0

        while start < length:
            end = start + stride
            subset = dataframe.iloc[start:end]
            list_of_df.append(subset)
            start = end
            
        return list_of_df
    #endregion