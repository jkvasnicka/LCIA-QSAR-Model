'''
This module contains the `ResultsAnalyzer` class, which is responsible for 
analyzing the results of the modeling workflows. It includes functionalities 
for in-sample and out-of-sample predictions, feature importance analysis, and 
other result-related tasks.
'''

import pandas as pd 
import numpy as np

from feature_selection import FeatureSelector

# NOTE: For backwards compatibility
from plotting import sensitivity_analysis  

#region: ResultsAnalyzer.__init__
class ResultsAnalyzer:
    '''
    A class to analyze the results of machine learning models.

    This class provides methods to obtain in-sample and out-of-sample 
    predictions, determine important features, and perform other 
    result-related analyses.
    '''
    def __init__(self, results_manager, data_manager, plot_settings):
        '''
        Initialize the ResultsAnalyzer class.

        Parameters
        ----------
        results_manager : A `ResultsManager` instance
        data_manager : A `DataManager` instance
        plot_settings : SimpleNamespace
            Configuration settings related to plotting.
        '''
        self.results_manager = results_manager
        self.data_manager = data_manager
        self.plot_settings = plot_settings
#endregion

    # FIXME: Appears that inverse_transform only applied to y_pred, not y_true?
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

        y_pred, X = self._get_prediction(model_key, X, inverse_transform)

        return y_pred, X, y_true
    #endregion

    # TODO: Add optional inverse_transform?
    #region: get_out_sample_prediction
    def get_out_sample_prediction(self, model_key, aggregation='mean'):
        '''
        Get out-of-sample aggregated predictions for the given model key.

        Aggregates predictions across cross-validation replicates for each
        chemical, providing a single prediction per chemical based on the 
        specified aggregation method (e.g., mean).

        Parameters
        ----------
        model_key : Tuple
            Key identifying the model for which predictions are required.
        aggregation : str
            Type of aggregation to apply ('mean', 'median', etc.). Must be a 
            valid method of pd.core.groupby.GroupBy.

        Returns
        -------
        y_pred_agg : pandas.Series
            Aggregated predicted target values.
        y_true : pandas.Series
            True target values.
        '''
        # Load the observed values for comparison
        model_key_names = self.results_manager.read_model_key_names()
        key_for = dict(zip(model_key_names, model_key))
        y_true = self.data_manager.load_target(**key_for)

        # Get the out-of-sample predictions
        predictions = self.results_manager.read_result(model_key, 'predictions').squeeze()

        if not hasattr(pd.core.groupby.GroupBy, aggregation):
            raise ValueError(f"Aggregation method '{aggregation}' is not valid.")

        # Perform the aggregation
        group = predictions.groupby(level=0)
        y_pred_agg = getattr(group, aggregation)()

        prediction_chemicals = list(y_pred_agg.index.unique(level=0))
        return y_pred_agg, y_true[prediction_chemicals]
    #endregion

    #region: predict
    def predict(
            self, 
            model_key, 
            inverse_transform=False, 
            exclude_training=False
            ):
        '''
        Make prediction for the given model key.

        Parameters
        ----------
        model_key : Tuple
            Key identifying the model for which predictions are required.
        inverse_transform : bool, optional
            If True, applies the inverse transform to the predictions 
            (default is False).
        exclude_training : bool, optional
            If True, excludes chemicals used for model training. Default is 
            False; predictions are made for all chemicals with features.

        Returns
        -------
        y_pred : pandas.Series
            Predicted target values.
        X : pandas.DataFrame
            Features used for prediction.
        '''
        model_key_names = self.results_manager.read_model_key_names()
        key_for = dict(zip(model_key_names, model_key))

        X = self.data_manager.load_features(
            **key_for, 
            exclude_training=exclude_training
            )

        y_pred, X = self._get_prediction(model_key, X, inverse_transform)

        return y_pred, X
    #endregion

    #region: _get_prediction
    def _get_prediction(self, model_key, X, inverse_transform=False):
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

    #region: prediction_interval
    @staticmethod
    def prediction_interval(prediction, error, z_score=1.645):
        '''
        Calculate the prediction interval.

        Parameters
        ----------
        prediction : pd.Series
            Predicted values in log10 scale.
        error : float
            Measure of uncertainty, such as the Root Mean Squared Error.

        Returns
        -------
        lower_bound : pd.Series
            Lower bound of the prediction interval.
        upper_bound : pd.Series
            Upper bound of the prediction interval.
        '''
        lower_bound = prediction - z_score*error
        upper_bound = prediction + z_score*error
        return lower_bound, upper_bound
    #endregion

    #region: get_typical_pod_error
    def get_typical_pod_error(
            self, 
            model_key,
            metric='root_mean_squared_error'
            ):
        '''
        Helper function to get the typical POD prediction error.

        This error can be used to derive the POD prediction interval.

        Returns
        -------
        float
            The median RMSE from cross validation.

        See Also
        --------
        ResultsAnalyzer.prediction_interval()
        '''
        typical_rmse = (
            self.read_result(model_key, 'performances')[metric]
            .quantile()
        )
        return typical_rmse
    #endregion

    #region: pod_and_prediction_interval
    def pod_and_prediction_interval(
            self, 
            model_key, 
            inverse_transform=False, 
            normalize=False, 
            exclude_training=True
            ):
        '''
        Compute Points of Departure (PODs) with uncertainty estimates.

        Parameters
        ----------
        model_key : tuple
            Key identifying the model to be analyzed.
        inverse_transform : bool, optional
            If True, applies the inverse transform to the predictions 
            (default is False).
        normalize : bool, optional
            If True, return cumulative frequencies (proportions) instead of 
            counts.
        exclude_training : bool, optional
            If True, excludes chemicals used for model training. Default is 
            True, because these chemicals already have labeled data.

        Returns
        -------
        pandas.DataFrame
            - `pod` : sorted Points of Departure.
            - `cum_count`: Cumulative counts for the sorted PODs.
            - `lb`: Lower bound of the 90% prediction interval.
            - `ub`: Upper bound of the 90% prediction interval.
        '''
        y_pred, *_ = self.predict(model_key, exclude_training=exclude_training)
        sorted_pods, cumulative_data = self.generate_cdf_data(
            y_pred, 
            normalize=normalize
            )
        
        rmse = self.get_typical_pod_error(model_key)  # log10-units
        lb, ub = self.prediction_interval(sorted_pods, rmse)
            
        if inverse_transform:
            sorted_pods, lb, ub = ResultsAnalyzer._inverse_log10(
                sorted_pods, lb, ub
                )

        pod_data = {
            'pod' : sorted_pods,
            'lb' : lb,
            'ub' : ub
            }
        ResultsAnalyzer._insert_cumulative_data(
            pod_data, 
            cumulative_data, 
            normalize
            )
        
        return pd.DataFrame(pod_data)
    #endregion

    #region: moe_and_prediction_intervals
    def moe_and_prediction_intervals(
            self, 
            model_key,
            inverse_transform=False, 
            normalize=False,
            exclude_training=True           
            ):
        '''
        Compute Margins of Exposure (MOEs) with uncertainty estimates.

        Two primary sources of uncertainty are addressed:
            1. Predicted PODs (hazard uncertainty) represented by a 90% 
               prediction interval.
            2. Exposure estimates, reflected by examining MOEs at different 
               exposure percentiles.
        
        Parameters
        ----------
        model_key : tuple
            Key identifying the model to be analyzed.
        inverse_transform : bool, optional
            If True, applies the inverse transform to the predictions 
            (default is False).
        normalize : bool, optional
            If True, return cumulative frequencies (proportions) instead of 
            counts.
        exclude_training : bool, optional
            If True, excludes chemicals used for model training. Default is 
            True, because these chemicals already have labeled data.
        
        Returns
        -------
        dict of pandas.DataFrame
            A dictionary where keys are exposure percentiles. 
            Each corresponding value is a DataFrame containing:
            - `moe`: Sorted Margins of Exposure.
            - `cum_count`: Cumulative counts for the sorted MOEs.
            - `lb`: Lower bound of the 90% prediction interval.
            - `ub`: Upper bound of the 90% prediction interval.
        '''
        y_pred, *_ = self.predict(model_key, exclude_training=exclude_training)
        
        exposure_df = self.data_manager.load_exposure_data()
        moes = self.margins_of_exposure(y_pred, exposure_df)

        rmse = self.get_typical_pod_error(model_key)  # log10-units
        
        results_for_percentile = {}  # initialize
        
        for percentile in exposure_df.columns:
            
            sorted_moes, cumulative_data = self.generate_cdf_data(
                moes[percentile],
                normalize=normalize
                )
            
            lb, ub = self.prediction_interval(sorted_moes, rmse)
            
            if inverse_transform:
                sorted_moes, lb, ub = ResultsAnalyzer._inverse_log10(
                    sorted_moes, lb, ub
                    )

            moe_data = {
                    'moe': sorted_moes,
                    'lb': lb,
                    'ub': ub
                    }
            ResultsAnalyzer._insert_cumulative_data(
                moe_data, 
                cumulative_data, 
                normalize
                )
            results_for_percentile[percentile] = pd.DataFrame(moe_data)
            
        return results_for_percentile
    #endregion

    #region: generate_cdf_data
    @staticmethod
    def generate_cdf_data(data_series, normalize=False):
        '''
        Generate sorted values and their cumulative counts (or frequencies) for 
        CDF plotting.

        Parameters
        ----------
        data_series : pd.Series
            The data series to generate CDF data from.
        normalize : bool, optional
            If True, return cumulative frequencies (proportions) instead of 
            counts.

        Returns
        -------
        sorted_values : pd.Series
            Sorted values from the input data series.
        cumulative_data : np.ndarray
            Cumulative counts or frequencies for the sorted values.
        '''
        data_series = data_series.dropna()
        
        sorted_values = data_series.sort_values()
        cumulative_counts = np.arange(1, len(sorted_values) + 1)
        
        if normalize:
            cumulative_data = cumulative_counts / len(sorted_values)
        else:
            cumulative_data = cumulative_counts
            
        return sorted_values, cumulative_data
    #endregion

    #region: margins_of_exposure
    @staticmethod
    def margins_of_exposure(pods, exposures, log10_units=True):
        '''
        Compute the margins of exposure (MOE) between predicted effects (pods) and 
        exposures. The function aligns the indices of pods and exposures, keeping 
        only their intersection, and computes the MOE accordingly.

        Parameters
        ----------
        pods : pandas.Series
            Predicted points of departure, indexed by chemical identifier.
        exposures : pandas.DataFrame or pandas.Series
            Exposure data, indexed by chemical identifier. If a DataFrame, each 
            column represents a different exposure estimate.
        log10_units : bool, optional
            If True, computes the MOE in log10 units (default is True). If False,
            returns the MOE in original units.

        Returns
        -------
        pandas.DataFrame or pandas.Series
            Margins of exposure, with the same shape as exposures, containing the 
            MOE values for the aligned indices.

        Notes
        -----
        The function aligns the indices of pods and exposures using an inner join,
        meaning that only the overlapping indices are included in the result.
        '''
        pods_aligned, exposures_aligned = pods.align(exposures, join='inner')

        operation = np.subtract if log10_units else np.divide

        if isinstance(exposures_aligned, pd.DataFrame):
            moe = exposures_aligned.apply(
                lambda col: operation(pods_aligned, col), 
                axis=0
                )
        else:
            moe = operation(pods_aligned, exposures_aligned)

        return moe
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

        ## Reproduce the feature selection using the stored settings

        config = self.results_manager.read_configuration()
        args = (
            config['feature_selection']['criterion_metric'],
            config['feature_selection']['n_features']
        )
        feature_names = (
            FeatureSelector.select_features(result_df, *args)
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

        ## Reproduce the feature selection using the stored settings
        
        config = self.results_manager.read_configuration()

        stride = (
            config['feature_selection']['n_splits_select']
            * config['feature_selection']['n_repeats_select'] 
            * config['feature_selection']['n_repeats_perm']
        )
        args = (
            config['feature_selection']['criterion_metric'],
            config['feature_selection']['n_features']
        )

        list_of_df = ResultsAnalyzer.split_replicates(result_df, stride)
        feature_names_for_replicate = {
            i : FeatureSelector.select_features(result_df, *args) 
            for i, result_df in enumerate(list_of_df)
            }
        
        return feature_names_for_replicate
    #endregion

    #region: get_pod_comparison_data
    def get_pod_comparison_data(self, model_key):
        '''
        Retrieve Point of Departure (POD) comparison data.
        
        Parameters
        ----------
        model_key : tuple
            The model key for which to retrieve the POD data.
            
        Returns
        -------
        dict
            A dictionary containing POD data for the given model key. The 
            dictionary has keys 'Authoritative', 'ToxValDB', and 'QSAR', each 
            mapping to a corresponding data series.

        See Also
        --------
        plot.cumulative_pod_distributions()
        '''        
        model_key_names = self.read_model_key_names()
        key_for = dict(zip(model_key_names, model_key))
        
        y_auth = (
            self.load_authoritative_pods()
            [key_for['target_effect']]
            .dropna()
        )
        _, y_true = self.data_manager.load_features_and_target(**key_for)
        y_pred, _ = self.predict(model_key)
        
        y_for_label = {
            self.plot_settings.authoritative_label: y_auth,
            self.plot_settings.surrogate_label: y_true,
            self.plot_settings.qsar_label: y_pred
        }
        
        return y_for_label
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

    #region: summarize_model_performances
    def summarize_model_performances(self, model_keys=None, quantiles=None):
        '''
        Generate a statistical summary table comparing performance scores of each 
        model.

        Parameters
        ----------
        model_keys : list of tuple, optional
            List of model keys for which to retrieve the results. If None, 
            then all model keys will be used.
        quantiles : float or array-like, optional
            Value between 0 <= q <= 1, the quantile(s) to compute. Defaults to 90%
            and 95% confidence intervals.
            
        Returns
        -------
        pandas.DataFrame
            The index has three levels: effect, model_name, metric. The columns are
            the quantiles.
        '''
        if not quantiles:
            quantiles = [0.025, 0.05, 0.5, 0.95, 0.975]  # by default

        performances = self.results_manager.combine_results(
            'performances', 
            model_keys=model_keys
        )
        # Get the results for the metrics of interest
        metrics = list(self.plot_settings.label_for_metric)
        performances = performances.loc[
            :, performances.columns.get_level_values('metric').isin(metrics)
        ]
        # Use the nice labels in the config file
        performances = performances.rename(
            self.plot_settings.label_for_metric, 
            level='metric', 
            axis=1
        )

        model_key_names = self.results_manager.read_model_key_names()

        performances_for = {}  # initialize

        for effect, effect_label in self.plot_settings.label_for_effect.items():
            performances_for[effect_label] = sensitivity_analysis.prepare_data_for_plotting(
                performances, 
                effect, 
                self.data_manager, 
                model_key_names, 
                self.plot_settings
            )

        # Create a statistical summary table
        performance_summary = (
            pd.concat(performances_for, axis=1)
            .quantile(quantiles)
            .T
        )
        # Name the first index level
        performance_summary.index.names = ['effect'] + performance_summary.index.names[1:]

        return performance_summary
    #endregion

    #region: describe
    def describe(self, model_key, result_type, percentiles=None):
        '''
        Describe model performances by generating a summary of selected 
        metrics.

        Parameters
        ----------
        model_key : str
            Identifier for the model to summarize.
        result_type : str
            Specifies the type of results to describe.
        percentiles : list of float, optional
            The percentiles to include in the output. Uses pandas default.

        Returns
        -------
        pandas.DataFrame
        '''
        if 'importances' in result_type:
            metrics = list(self.plot_settings.label_for_scoring)
        else: 
            metrics = list(self.plot_settings.label_for_metric)

        performances = self.read_result(model_key, result_type)

        if 'root_mean_squared_error' in metrics:
            metrics.append('gsd')
            metrics.append('gsd_squared')
            rmse = performances['root_mean_squared_error']
            gsd, gsd_squared = self._calculate_gsd_with_confidence(rmse)
            performances['gsd'] = gsd
            performances['gsd_squared'] = gsd_squared

        return performances.describe(percentiles=percentiles)[metrics]
    #endregion

    #region: _calculate_gsd_with_confidence
    @staticmethod
    def _calculate_gsd_with_confidence(rmse, z_score=1.96):
        '''
        Calculate the geometric standard deviation (GSD) and its 
        confidence-adjusted value.

        Parameters
        ----------
        rmse : float
            The root mean squared error from which the GSD is derived.
        z_score : float, optional
            The z-score corresponding to the desired confidence interval. 
            Defaults to 1.96, which corresponds to approximately a 95% 
            confidence interval.
        '''
        gsd = 10 ** rmse  # in natural units
        gsd_adjusted = gsd ** z_score
        return gsd, gsd_adjusted
    #endregion

    #region: read_model_keys
    def read_model_keys(
            self, 
            inclusion_string=None, 
            exclusion_string=None
            ):
        '''Refer to `ResultsManager.read_model_keys` for documentation'''
        return self.results_manager.read_model_keys(
            inclusion_string, 
            exclusion_string
            )
    #endregion

    #region: group_model_keys
    def group_model_keys(
            self, 
            exclusion_key_names, 
            string_to_exclude=None, 
            model_keys=None,
            filter_single_key=True
            ):
        '''Refer to `ResultsManager.group_model_keys` for documentation'''
        return self.results_manager.group_model_keys(
            exclusion_key_names, 
            string_to_exclude, 
            model_keys,
            filter_single_key
            )
    #endregion

    #region: read_model_key_names
    def read_model_key_names(self):
        '''Refer to `ResultsManager.read_model_key_names` for documentation'''
        return self.results_manager.read_model_key_names()
#endregion

    #region: read_result
    def read_result(self, model_key, result_type):
        '''Refer to `ResultsManager` for documentation'''
        return self.results_manager.read_result(model_key, result_type)
#endregion

    #region: combine_results   
    def combine_results(self, result_type, model_keys=None):
        '''Refer to `ResultsManager.combine_results` for documentation'''
        return self.results_manager.combine_results(
            result_type, 
            model_keys=model_keys
            )
    #endregion

    #region: load_features_and_target    
    def load_features_and_target(self, *args, **kwargs):
        '''
        Refer to `DataManager.load_features_and_target` for documentation
        '''
        return self.data_manager.load_features_and_target(*args, **kwargs)
    #endregion

    #region: load_features
    def load_features(self, *args, **kwargs):
        '''Refer to `DataManager.load_features` for documentation'''
        return self.data_manager.load_features(*args, **kwargs)
    #endregion

    #region: load_target
    def load_target(self, *args, **kwargs):
        '''Refer to `DataManager.load_target` for documentation'''
        return self.data_manager.load_target(*args, **kwargs)
    #endregion

    #region: load_authoritative_pods
    def load_authoritative_pods(self):
        '''Refer to `DataManager.load_authoritative_pods` for documentation'''
        return self.data_manager.load_authoritative_pods()
    #endregion

    #region: load_oral_equivalent_doses
    def load_oral_equivalent_doses(self):
        '''
        Refer to `DataManager.load_oral_equivalent_doses` for documentation
        '''
        return self.data_manager.load_oral_equivalent_doses()
    #endregion

    #region: _inverse_log10
    @staticmethod
    def _inverse_log10(sorted_values, lb, ub):
        '''
        Helper function to transform data from log10-units to natural units.
        '''
        return (
            10**sorted_values, 
            10**lb, 
            10**ub
        )
    #endregion

    #region: _insert_cumulative_data
    @staticmethod
    def _insert_cumulative_data(data_dict, cumulative_data, normalize):
        '''
        Helper function to insert cumulative data into a dictionary. 

        The key is determined based on whether the data were normalized.
        '''
        if normalize:
            data_dict['cum_freq'] = cumulative_data
        else:
            data_dict['cum_count'] = cumulative_data
    #endregion